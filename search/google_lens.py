"""Google Lens visual search provider using browser automation."""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import (
    SEARCH_HEADLESS,
    SEARCH_TIMEOUT_MS,
    MAX_SEARCH_CANDIDATES,
    USER_AGENT,
)
from extraction.url_utils import extract_domain, normalize_url
from .base import SearchCandidate, SearchProvider
from .models import SearchResponse, SearchStatus

logger = logging.getLogger(__name__)

GOOGLE_INTERNAL_DOMAINS = {
    "google.com",
    "google.co.in",
    "google.co.uk",
    "gstatic.com",
    "youtube.com/howyoutubeworks",
    "policies.google.com",
    "support.google.com",
    "accounts.google.com",
}

CHROMIUM_SERVER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
]


class GoogleLensProvider(SearchProvider):
    """Executes live visual reverse-image search via Google Lens."""

    @property
    def name(self) -> str:
        return "google"

    def search_detailed(self, image_path: str) -> SearchResponse:
        t0 = time.time()
        logger.info("SELECTED PROVIDER: google")
        logger.info("NORMALIZED PROVIDER: google")
        logger.info("PROVIDER IMPLEMENTATION: GoogleLensProvider")

        path_obj = Path(image_path).resolve()
        if not path_obj.is_file():
            err_msg = f"Input image does not exist: {path_obj}"
            return SearchResponse(
                provider="google",
                status=SearchStatus.UNAVAILABLE,
                elapsed_seconds=round(time.time() - t0, 2),
                error=err_msg,
            )

        is_render = bool(os.getenv("RENDER") or os.getenv("SERVER_SOFTWARE"))
        use_headless = True if (is_render or os.name != "nt") else SEARCH_HEADLESS

        candidates: List[SearchCandidate] = []
        seen_urls = set()
        raw_count = 0
        diagnostics: Dict[str, Any] = {
            "headless": use_headless,
            "render_detected": is_render,
        }

        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(
                        headless=use_headless,
                        args=CHROMIUM_SERVER_ARGS,
                    )
                except Exception as b_err:
                    err = f"Failed to launch Chromium for Google Lens: {b_err}"
                    logger.error(err)
                    return SearchResponse(
                        provider="google",
                        status=SearchStatus.BROWSER_ERROR,
                        elapsed_seconds=round(time.time() - t0, 2),
                        error=err,
                        diagnostics=diagnostics,
                    )

                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 900},
                    accept_downloads=False,
                )
                page = context.new_page()

                try:
                    logger.info("Navigating to Google Lens interface...")
                    # Route abort landing page media for fast commit
                    page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] and "search" not in page.url else route.continue_())

                    try:
                        page.goto("https://images.google.com", timeout=15000, wait_until="commit")
                    except Exception as e:
                        logger.warning(f"Google images navigation commit slow ({e}), trying lens.google.com...")
                        page.goto("https://lens.google.com/upload", timeout=15000, wait_until="commit")

                    page.wait_for_timeout(1000)
                    self._dismiss_consent_popups(page)

                    # Check for bot challenge
                    if "sorry/index" in page.url or "recaptcha" in page.content().lower():
                        return SearchResponse(
                            provider="google",
                            status=SearchStatus.PROVIDER_BLOCKED,
                            elapsed_seconds=round(time.time() - t0, 2),
                            error="Google presented a CAPTCHA challenge in this cloud environment. Cloud datacenter IPs are frequently restricted by Google Lens. Switch to 'bing' in the sidebar.",
                        )

                    file_input = page.query_selector('input[type="file"]')
                    if not file_input:
                        camera_btn = page.query_selector('div[aria-label*="Search by image"], button[aria-label*="Search by image"], [data-base-lens-url]')
                        if camera_btn:
                            camera_btn.click()
                            page.wait_for_timeout(1000)
                            file_input = page.query_selector('input[type="file"]')

                    if not file_input:
                        return SearchResponse(
                            provider="google",
                            status=SearchStatus.PARSER_FAILURE,
                            elapsed_seconds=round(time.time() - t0, 2),
                            error="Could not locate image upload element on Google Lens. Cloud datacenter IPs are frequently restricted by Google. Switch to 'bing' in the sidebar.",
                        )

                    logger.info(f"Uploading query image: {path_obj.name}")
                    try:
                        page.unroute("**/*")
                    except Exception:
                        pass

                    file_input.set_input_files(str(path_obj))
                    page.wait_for_timeout(3500)

                    try:
                        page.wait_for_selector('a[href^="http"]', timeout=15000)
                    except PlaywrightTimeoutError:
                        pass

                    page.wait_for_timeout(2500)

                    links_data = page.evaluate("""() => {
                        const results = [];
                        const anchors = Array.from(document.querySelectorAll('a[href^="http"]'));
                        for (const a of anchors) {
                            const href = a.href;
                            if (!href) continue;
                            try {
                                const urlObj = new URL(href);
                                if (urlObj.hostname.includes('google.') || urlObj.hostname.includes('gstatic.')) continue;
                            } catch(e) { continue; }

                            let imgUrl = null;
                            const img = a.querySelector('img') || a.parentElement?.querySelector('img');
                            if (img) {
                                imgUrl = img.src || img.getAttribute('data-src') || null;
                            }

                            let title = a.innerText || a.getAttribute('aria-label') || a.getAttribute('title') || '';
                            title = title.replace(/\\s+/g, ' ').trim();

                            results.push({ url: href, title: title, image_url: imgUrl, thumbnail_url: imgUrl });
                        }
                        return results;
                    }""")

                    raw_count = len(links_data)
                    rank = 1
                    for item in links_data:
                        raw_url = item.get("url", "").strip()
                        if not raw_url:
                            continue

                        domain = extract_domain(raw_url)
                        if not domain or any(d in domain for d in GOOGLE_INTERNAL_DOMAINS):
                            continue

                        norm_url = normalize_url(raw_url)
                        if norm_url in seen_urls:
                            continue
                        seen_urls.add(norm_url)

                        title = item.get("title") or f"Visual Match on {domain}"
                        if len(title) > 120:
                            title = title[:117] + "..."

                        candidates.append(
                            SearchCandidate(
                                url=raw_url,
                                title=title,
                                source_domain=domain,
                                search_rank=rank,
                                thumbnail_url=item.get("thumbnail_url"),
                                image_url=item.get("image_url"),
                            )
                        )
                        rank += 1
                        if len(candidates) >= MAX_SEARCH_CANDIDATES:
                            break

                except Exception as ex:
                    logger.error(f"Google Lens execution error: {ex}")
                    return SearchResponse(
                        provider="google",
                        status=SearchStatus.NETWORK_ERROR,
                        elapsed_seconds=round(time.time() - t0, 2),
                        error=str(ex),
                    )
                finally:
                    context.close()
                    browser.close()

        except Exception as e:
            return SearchResponse(
                provider="google",
                status=SearchStatus.BROWSER_ERROR,
                elapsed_seconds=round(time.time() - t0, 2),
                error=str(e),
            )

        elapsed = round(time.time() - t0, 2)
        if candidates:
            status = SearchStatus.SUCCESS
            error = None
        elif raw_count > 0:
            status = SearchStatus.PARSER_FAILURE
            error = f"Google Lens returned {raw_count} raw links, but none met domain criteria."
        else:
            status = SearchStatus.NO_RESULTS
            error = "Google Lens search completed, but no usable candidates were discovered."

        return SearchResponse(
            provider="google",
            status=status,
            elapsed_seconds=elapsed,
            raw_results_count=raw_count,
            parsed_candidates_count=len(candidates),
            candidates=candidates,
            error=error,
            diagnostics=diagnostics,
        )

    def _dismiss_consent_popups(self, page) -> None:
        """Dismisses typical cookie and GDPR consent banners."""
        consent_selectors = [
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'button:has-text("Agree")',
            'button:has-text("Accept")',
            'form[action*="consent"] button',
            'div[role="dialog"] button:has-text("Accept")',
        ]
        for selector in consent_selectors:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass
