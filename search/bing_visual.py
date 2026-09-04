"""Bing Visual Search provider — fast implementation via bing.com/images."""

import base64
import io
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse, parse_qs

from PIL import Image
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import config
from config import (
    SEARCH_HEADLESS,
    MAX_SEARCH_CANDIDATES,
    USER_AGENT,
)
from extraction.url_utils import extract_domain, normalize_url
from .base import SearchCandidate, SearchProvider
from .models import SearchResponse, SearchStatus

logger = logging.getLogger(__name__)

BING_INTERNAL_DOMAINS = {
    "bing.com",
    "microsoft.com",
    "live.com",
    "msn.com",
    "microsofttranslator.com",
    "bingplaces.com",
    "r.bing.com",
}

# Maximum upload dimension (px) — smaller = faster upload
MAX_UPLOAD_PX = 800

BING_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.bing.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CHROMIUM_SERVER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
    "--disable-extensions",
]

# Analytics/telemetry hosts to block for speed
BLOCKED_URL_PATTERNS = [
    "bat.bing.com",
    "clarity.ms",
    "c.bing.com",
    "bing.com/fd/ls",
    "OneCollector",
    "explore.microsoft.com",
    "js.monitor.azure.com",
]


def _decode_bing_redirect(href: str) -> str:
    """Decode obfuscated Bing redirect URLs (bing.com/ck/a?...&u=a1<base64>)."""
    if not href:
        return ""
    if "bing.com/ck/a" in href:
        try:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            u_val = qs.get("u", [""])[0]
            if u_val.startswith("a1"):
                b64 = u_val[2:]
                # Fix padding
                b64 += "=" * ((4 - len(b64) % 4) % 4)
                decoded = base64.urlsafe_b64decode(b64).decode("utf-8", errors="ignore")
                if decoded.startswith("http"):
                    return decoded
        except Exception:
            pass
    return href


class BingVisualProvider(SearchProvider):
    """Executes live visual reverse-image search via Bing Images (fast path)."""

    @property
    def name(self) -> str:
        return "bing"

    def _prepare_image(self, path_obj: Path) -> Path:
        """Resize image to max 800px and save as optimized JPEG for fast upload."""
        im = Image.open(path_obj).convert("RGB")
        if max(im.size) > MAX_UPLOAD_PX:
            im.thumbnail((MAX_UPLOAD_PX, MAX_UPLOAD_PX), Image.LANCZOS)
        out_path = config.CACHE_DIR / "_bing_upload_tmp.jpg"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(out_path, format="JPEG", quality=82)
        return out_path

    def search_detailed(self, image_path: str) -> SearchResponse:
        t0 = time.time()
        logger.info("SELECTED PROVIDER: bing")
        logger.info("NORMALIZED PROVIDER: bing")
        logger.info("PROVIDER IMPLEMENTATION: BingVisualProvider (fast)")

        path_obj = Path(image_path).resolve()
        if not path_obj.is_file():
            err_msg = f"Input image does not exist: {path_obj}"
            return SearchResponse(
                provider="bing",
                status=SearchStatus.UNAVAILABLE,
                elapsed_seconds=round(time.time() - t0, 2),
                error=err_msg,
            )

        upload_path = self._prepare_image(path_obj)

        is_render = bool(os.getenv("RENDER") or os.getenv("SERVER_SOFTWARE"))
        use_headless = True if (is_render or os.name != "nt") else SEARCH_HEADLESS

        candidates: List[SearchCandidate] = []
        raw_count = 0
        diagnostics: Dict[str, Any] = {
            "headless": use_headless,
            "render_detected": is_render,
            "method": "bing_images_fast",
        }

        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(
                        headless=use_headless,
                        args=CHROMIUM_SERVER_ARGS,
                    )
                except Exception as b_err:
                    err = f"Failed to launch Chromium for Bing: {b_err}"
                    logger.error(err)
                    return SearchResponse(
                        provider="bing",
                        status=SearchStatus.BROWSER_ERROR,
                        elapsed_seconds=round(time.time() - t0, 2),
                        error=err,
                        diagnostics=diagnostics,
                    )

                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                )
                page = context.new_page()

                # Block analytics/telemetry hosts to prevent network hangs
                def _route_handler(route):
                    url = route.request.url
                    if any(pattern in url for pattern in BLOCKED_URL_PATTERNS):
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", _route_handler)

                try:
                    logger.info("Navigating to https://www.bing.com/images ...")
                    page.goto(
                        "https://www.bing.com/images",
                        wait_until="domcontentloaded",
                        timeout=12000,
                    )
                    logger.info(f"Bing images loaded in {time.time()-t0:.2f}s")

                    # Dismiss cookie/consent popup if present
                    self._dismiss_popups(page)

                    # Click the camera (visual search) button to reveal file input
                    cam_sel = (
                        "#sb_imgsearch, #sbi_b, "
                        '[aria-label*="Visual search"], '
                        '[aria-label*="Search using an image"]'
                    )
                    cam = page.query_selector(cam_sel)
                    if cam:
                        cam.click()
                        page.wait_for_timeout(500)

                    # Locate file input — may be hidden so use state="attached"
                    file_input = page.query_selector('input[type="file"]')
                    if not file_input:
                        try:
                            file_input = page.wait_for_selector(
                                'input[type="file"]',
                                state="attached",
                                timeout=4000,
                            )
                        except PlaywrightTimeoutError:
                            pass

                    if not file_input:
                        return SearchResponse(
                            provider="bing",
                            status=SearchStatus.PARSER_FAILURE,
                            elapsed_seconds=round(time.time() - t0, 2),
                            error="Could not locate file upload input on Bing Images.",
                            diagnostics=diagnostics,
                        )

                    logger.info(f"Uploading image ({upload_path.stat().st_size} bytes)...")
                    file_input.set_input_files(str(upload_path))

                    # Wait for results page URL (bcid= param indicates image search landed)
                    logger.info("Waiting for Bing search results...")
                    results_reached = False
                    for i in range(10):
                        page.wait_for_timeout(1000)
                        curr_url = page.url
                        if (
                            "bcid=" in curr_url
                            or "images/search" in curr_url
                            or ("search?" in curr_url and "q=" in curr_url)
                        ):
                            results_reached = True
                            logger.info(
                                f"Bing results URL at {time.time()-t0:.2f}s: {curr_url[:80]}"
                            )
                            break

                    if not results_reached:
                        logger.warning(
                            f"Bing results URL not reached after 10s. Current URL: {page.url[:80]}"
                        )

                    # Give page extra 1.5s to render results
                    page.wait_for_timeout(1500)

                    # Extract results: organic web results + OIP image thumbnails
                    raw_items = page.evaluate("""() => {
                        const out = [];
                        const seen = new Set();

                        // 1. Organic web results (.b_algo) with thumbnails
                        for (const algo of document.querySelectorAll('.b_algo, li.b_algo')) {
                            const a = algo.querySelector('h2 a, a[href*="/ck/a"], a');
                            const h2 = algo.querySelector('h2, .b_algo_title, .b_title');
                            const img = algo.querySelector('img');
                            const href = a ? a.href : '';
                            const title = h2 ? h2.innerText.trim() : (a ? a.innerText.trim() : '');
                            const imgSrc = img ? (img.src || img.getAttribute('data-src') || '') : '';
                            if (href && !seen.has(href)) {
                                seen.add(href);
                                out.push({href, title, imgSrc});
                            }
                        }

                        // 2. Visual image matches with OIP thumbnails
                        for (const img of document.querySelectorAll('img')) {
                            const src = img.src || img.getAttribute('data-src') || '';
                            if (!src) continue;
                            const isOIP = src.includes('th.bing.com/th/id/OIP') || src.includes('th?id=OIP');
                            if (!isOIP) continue;
                            if (seen.has(src)) continue;
                            seen.add(src);

                            const parentA = img.closest('a');
                            const card = img.closest('.iacf_item, .b_algo, .richCard, .mm_item');
                            let title = '';
                            if (card) {
                                const t = card.querySelector('h2, .title, .b_title, .caption');
                                if (t) title = t.innerText.replace(/\\n+/g, ' ').trim();
                            }
                            out.push({
                                href: parentA ? parentA.href : '',
                                title: title || 'Visual Match',
                                imgSrc: src
                            });
                        }

                        return out;
                    }""")

                    raw_count = len(raw_items)
                    logger.info(f"Bing raw items extracted: {raw_count}")
                    candidates = self._build_candidates(raw_items)

                except PlaywrightTimeoutError as te:
                    return SearchResponse(
                        provider="bing",
                        status=SearchStatus.NETWORK_ERROR,
                        elapsed_seconds=round(time.time() - t0, 2),
                        error=f"Bing timed out: {te}",
                        diagnostics=diagnostics,
                    )
                except Exception as exc:
                    return SearchResponse(
                        provider="bing",
                        status=SearchStatus.NETWORK_ERROR,
                        elapsed_seconds=round(time.time() - t0, 2),
                        error=str(exc),
                        diagnostics=diagnostics,
                    )
                finally:
                    context.close()
                    browser.close()

        except Exception as e:
            return SearchResponse(
                provider="bing",
                status=SearchStatus.BROWSER_ERROR,
                elapsed_seconds=round(time.time() - t0, 2),
                error=str(e),
                diagnostics=diagnostics,
            )

        elapsed = round(time.time() - t0, 2)
        logger.info(f"Bing search finished in {elapsed}s — {len(candidates)} candidates")

        if candidates:
            status = SearchStatus.SUCCESS
            error = None
        elif raw_count > 0:
            status = SearchStatus.PARSER_FAILURE
            error = f"Bing returned {raw_count} raw links, but none met domain criteria."
        else:
            status = SearchStatus.NO_RESULTS
            error = "Bing search completed, but no usable candidates were discovered."

        return SearchResponse(
            provider="bing",
            status=status,
            elapsed_seconds=elapsed,
            raw_results_count=raw_count,
            parsed_candidates_count=len(candidates),
            candidates=candidates,
            error=error,
            diagnostics=diagnostics,
        )

    def _build_candidates(self, raw_items: list) -> List[SearchCandidate]:
        candidates: List[SearchCandidate] = []
        seen: set = set()
        rank = 1

        for item in raw_items:
            raw_href = (item.get("href") or "").strip()
            img_src = (item.get("imgSrc") or "").strip()
            title = (item.get("title") or "").strip()

            # Decode Bing's obfuscated redirect URLs
            decoded_url = _decode_bing_redirect(raw_href)

            # Prefer the decoded external URL; fall back to image URL
            page_url = decoded_url if (decoded_url and not any(d in decoded_url for d in BING_INTERNAL_DOMAINS)) else ""
            source_url = page_url or img_src

            if not source_url:
                continue

            norm = normalize_url(source_url)
            if norm in seen:
                continue
            seen.add(norm)

            domain = ""
            if page_url:
                extracted = extract_domain(page_url)
                if extracted and not any(d in extracted for d in BING_INTERNAL_DOMAINS):
                    domain = extracted
            if not domain and img_src:
                extracted = extract_domain(img_src)
                if extracted and not any(d in extracted for d in BING_INTERNAL_DOMAINS):
                    domain = extracted
            if not domain:
                domain = f"web-match-{rank}.org"

            if not title:
                title = f"Visual match on {domain}"
            if len(title) > 120:
                title = title[:117] + "..."

            # Only keep the thumbnail if it's from bing CDN (OIP = real thumbnail)
            thumb = img_src if (img_src and "th.bing.com" in img_src) else ""

            candidates.append(
                SearchCandidate(
                    url=source_url,
                    title=title,
                    source_domain=domain,
                    search_rank=rank,
                    thumbnail_url=thumb or None,
                    image_url=img_src or None,
                )
            )
            rank += 1
            if len(candidates) >= MAX_SEARCH_CANDIDATES:
                break

        return candidates

    def _dismiss_popups(self, page) -> None:
        for sel in [
            "#bnp_btn_accept",
            'button:has-text("Accept all")',
            'button:has-text("Accept")',
            'button:has-text("I agree")',
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(500)
                    break
            except Exception:
                pass
