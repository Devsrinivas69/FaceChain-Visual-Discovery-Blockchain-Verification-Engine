"""Google Lens visual search provider using browser automation."""

import logging
import time
from pathlib import Path
from typing import List
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

class GoogleLensProvider(SearchProvider):
    """Executes live visual reverse-image search via Google Lens."""

    @property
    def name(self) -> str:
        return "google_lens"

    def search(self, image_path: str) -> List[SearchCandidate]:
        path_obj = Path(image_path).resolve()
        if not path_obj.is_file():
            raise FileNotFoundError(f"Input image does not exist: {path_obj}")

        candidates: List[SearchCandidate] = []
        seen_urls = set()

        logger.info("Launching Playwright Chromium for Google Lens visual search...")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=SEARCH_HEADLESS,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
                accept_downloads=False,
            )
            page = context.new_page()

            try:
                # Approach A: Direct upload page
                logger.info("Navigating to Google Lens upload interface...")
                try:
                    page.goto("https://lens.google.com/upload", timeout=SEARCH_TIMEOUT_MS, wait_until="domcontentloaded")
                except Exception as e:
                    logger.warning(f"Lens upload page slow/errored ({e}), trying images.google.com...")
                    page.goto("https://images.google.com", timeout=SEARCH_TIMEOUT_MS, wait_until="domcontentloaded")

                # Handle consent / cookie popups if present
                self._dismiss_consent_popups(page)

                # Locate file input
                file_input = page.query_selector('input[type="file"]')
                if not file_input:
                    # If on images.google.com, click camera icon first
                    camera_btn = page.query_selector('div[aria-label*="Search by image"], button[aria-label*="Search by image"], [data-base-lens-url]')
                    if camera_btn:
                        camera_btn.click()
                        page.wait_for_timeout(1000)
                        file_input = page.query_selector('input[type="file"]')

                if not file_input:
                    logger.warning("Could not find file upload input on Google page.")
                    return []

                logger.info(f"Uploading query image: {path_obj.name}")
                file_input.set_input_files(str(path_obj))

                # Wait for search results container
                logger.info("Waiting for Google Lens visual results...")
                page.wait_for_timeout(3000)

                # Wait for result links or images
                try:
                    page.wait_for_selector('a[href^="http"]', timeout=SEARCH_TIMEOUT_MS)
                except PlaywrightTimeoutError:
                    logger.warning("Timeout waiting for result links in Google Lens.")

                # Extra settle time for dynamic JavaScript rendering
                page.wait_for_timeout(2500)

                # Extract candidate anchors and elements
                # Google Lens renders cards containing links to source pages and preview thumbnails
                links_data = page.evaluate("""
                    () => {
                        const results = [];
                        // Select all external links in result containers
                        const anchors = Array.from(document.querySelectorAll('a[href^="http"]'));
                        for (const a of anchors) {
                            const href = a.href;
                            if (!href) continue;

                            // Skip google domains
                            try {
                                const urlObj = new URL(href);
                                if (urlObj.hostname.includes('google.') || urlObj.hostname.includes('gstatic.')) {
                                    continue;
                                }
                            } catch(e) {
                                continue;
                            }

                            // Look for associated image inside or adjacent
                            let imgUrl = null;
                            const img = a.querySelector('img') || a.parentElement?.querySelector('img');
                            if (img) {
                                imgUrl = img.src || img.getAttribute('data-src') || null;
                            }

                            // Text title
                            let title = a.innerText || a.getAttribute('aria-label') || a.getAttribute('title') || '';
                            title = title.replace(/\\s+/g, ' ').trim();

                            results.push({
                                url: href,
                                title: title,
                                image_url: imgUrl,
                                thumbnail_url: imgUrl
                            });
                        }
                        return results;
                    }
                """)

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
                    # Truncate overly long text
                    if len(title) > 120:
                        title = title[:117] + "..."

                    cand = SearchCandidate(
                        url=raw_url,
                        title=title,
                        source_domain=domain,
                        search_rank=rank,
                        thumbnail_url=item.get("thumbnail_url"),
                        image_url=item.get("image_url"),
                    )
                    candidates.append(cand)
                    rank += 1

                    if len(candidates) >= MAX_SEARCH_CANDIDATES:
                        break

                logger.info(f"Google Lens discovered {len(candidates)} candidates.")

            except Exception as exc:
                logger.error(f"Google Lens execution encountered error: {exc}")
            finally:
                context.close()
                browser.close()

        return candidates

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
