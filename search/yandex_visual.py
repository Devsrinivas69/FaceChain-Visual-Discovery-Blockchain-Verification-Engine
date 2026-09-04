"""Yandex Visual Search provider using browser automation."""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from playwright.sync_api import sync_playwright, Error as PlaywrightError

from config import (
    SEARCH_HEADLESS,
    MAX_SEARCH_CANDIDATES,
    USER_AGENT,
)
from extraction.url_utils import extract_domain, normalize_url
from .base import SearchCandidate, SearchProvider
from .models import SearchResponse, SearchStatus

logger = logging.getLogger(__name__)

YANDEX_INTERNAL_DOMAINS = {
    "yandex.com",
    "yandex.ru",
    "ya.ru",
    "yastatic.net",
    "kinopoisk.ru",
    "auto.ru",
    "edadeal.ru",
    "market.yandex.ru",
}

# Essential flags for Chromium on Linux container / Render environments
CHROMIUM_SERVER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
]


class YandexVisualProvider(SearchProvider):
    """Executes live visual reverse-image search via Yandex Images."""

    @property
    def name(self) -> str:
        return "yandex"

    def search_detailed(self, image_path: str) -> SearchResponse:
        t0 = time.time()
        logger.info("SELECTED PROVIDER: yandex")
        logger.info("NORMALIZED PROVIDER: yandex")
        logger.info("PROVIDER IMPLEMENTATION: YandexVisualProvider")
        logger.info("Starting Yandex visual search")
        logger.info("Yandex provider initialized")

        path_obj = Path(image_path).resolve()
        if not path_obj.is_file():
            err_msg = f"Input image does not exist: {path_obj}"
            logger.error(err_msg)
            return SearchResponse(
                provider="yandex",
                status=SearchStatus.UNAVAILABLE,
                elapsed_seconds=round(time.time() - t0, 2),
                error=err_msg,
            )

        # Force headless mode on Render or non-Windows servers
        is_render = bool(os.getenv("RENDER") or os.getenv("SERVER_SOFTWARE"))
        use_headless = True if (is_render or os.name != "nt") else SEARCH_HEADLESS

        candidates: List[SearchCandidate] = []
        seen_urls = set()
        raw_count = 0
        diagnostics: Dict[str, Any] = {
            "headless": use_headless,
            "render_detected": is_render,
            "file_size": path_obj.stat().st_size,
        }

        try:
            logger.info("Yandex search request/browser started")
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(
                        headless=use_headless,
                        args=CHROMIUM_SERVER_ARGS,
                    )
                except Exception as b_err:
                    err = f"Failed to launch Chromium browser: {b_err}"
                    logger.error(err, exc_info=True)
                    return SearchResponse(
                        provider="yandex",
                        status=SearchStatus.BROWSER_ERROR,
                        elapsed_seconds=round(time.time() - t0, 2),
                        error=err,
                        diagnostics=diagnostics,
                    )

                context = browser.new_context(
                    viewport={"width": 1400, "height": 1000},
                    user_agent=USER_AGENT,
                )
                page = context.new_page()

                try:
                    # 1. Navigate to Yandex Images
                    logger.info("Navigating to https://yandex.com/images")
                    page.goto("https://yandex.com/images", timeout=35000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)

                    # 2. Check for bot verification / CAPTCHA
                    current_url = page.url.lower()
                    page_content = page.content().lower()
                    if (
                        "smartcaptcha" in current_url
                        or "showcaptcha" in current_url
                        or "captcha" in current_url
                        or "smartcaptcha" in page_content
                        or "checkbox-captcha" in page_content
                        or "robot" in page_content and "verification" in page_content
                    ):
                        err_msg = "Yandex presented a bot verification/CAPTCHA challenge."
                        logger.warning(err_msg)
                        return SearchResponse(
                            provider="yandex",
                            status=SearchStatus.PROVIDER_BLOCKED,
                            elapsed_seconds=round(time.time() - t0, 2),
                            error=err_msg,
                            diagnostics={"blocked_url": page.url},
                        )

                    # 3. Locate file input element
                    file_input = page.query_selector('input[type="file"]')
                    if not file_input:
                        # Try clicking the camera icon to reveal file input
                        camera_btn = page.query_selector('button[aria-label*="image"], .input__cbir-button, .cbir-button')
                        if camera_btn:
                            camera_btn.click()
                            page.wait_for_timeout(1000)
                            file_input = page.query_selector('input[type="file"]')

                    if not file_input:
                        err_msg = "Could not locate image upload element on Yandex page."
                        logger.warning(err_msg)
                        return SearchResponse(
                            provider="yandex",
                            status=SearchStatus.PARSER_FAILURE,
                            elapsed_seconds=round(time.time() - t0, 2),
                            error=err_msg,
                            diagnostics={"page_url": page.url},
                        )

                    # 4. Upload file
                    logger.info(f"Uploading file to Yandex: {path_obj.name}")
                    file_input.set_input_files(str(path_obj))

                    # 5. Wait for results page
                    results_reached = False
                    for i in range(25):
                        page.wait_for_timeout(1000)
                        curr = page.url
                        if "cbir_id" in curr or "rpt=imageview" in curr or "images/search" in curr:
                            results_reached = True
                            logger.info(f"Yandex results URL reached at second {i+1}: {curr[:80]}...")
                            break
                        # Also check if blocked during upload
                        if "captcha" in curr.lower():
                            return SearchResponse(
                                provider="yandex",
                                status=SearchStatus.PROVIDER_BLOCKED,
                                elapsed_seconds=round(time.time() - t0, 2),
                                error="Yandex presented a CAPTCHA challenge after image upload.",
                            )

                    page.wait_for_timeout(3500)

                    # 6. Extract candidate links
                    cards = page.evaluate("""() => {
                        const items = [];
                        const links = document.querySelectorAll('a[href^="http"]');
                        for (const a of links) {
                            const h = a.href;
                            if (!h || h.includes('yandex.') || h.includes('ya.ru') || h.includes('yastatic.')) continue;
                            
                            const img = a.querySelector('img') || a.parentElement?.querySelector('img');
                            const imgSrc = img ? (img.src || img.getAttribute('data-src') || img.getAttribute('data-thumb')) : null;
                            const isDirect = /\\.(jpg|jpeg|png|webp|avif)(\\?|$)/i.test(h);
                            
                            items.push({
                                url: h,
                                title: a.innerText ? a.innerText.slice(0, 80).replace(/\\n/g, ' ').trim() : '',
                                img: isDirect ? h : imgSrc,
                                is_direct: isDirect
                            });
                        }
                        return items;
                    }""")

                    raw_count = len(cards)
                    logger.info(f"Raw results discovered: {raw_count}")

                    # 7. Normalize and filter
                    rank = 1
                    for c in cards:
                        raw_url = (c.get("url") or "").strip()
                        if not raw_url:
                            continue

                        domain = extract_domain(raw_url)
                        if not domain or any(d in domain for d in YANDEX_INTERNAL_DOMAINS):
                            continue

                        norm = normalize_url(raw_url)
                        if norm in seen_urls:
                            continue
                        seen_urls.add(norm)

                        title = c.get("title") or f"Visual match on {domain}"
                        img_url = c.get("img") or (raw_url if c.get("is_direct") else None)

                        candidates.append(
                            SearchCandidate(
                                url=raw_url,
                                title=title,
                                source_domain=domain,
                                search_rank=rank,
                                thumbnail_url=img_url,
                                image_url=img_url,
                            )
                        )
                        rank += 1
                        if len(candidates) >= MAX_SEARCH_CANDIDATES:
                            break

                except PlaywrightError as p_err:
                    err_msg = f"Playwright error during Yandex visual search: {p_err}"
                    logger.error(err_msg)
                    return SearchResponse(
                        provider="yandex",
                        status=SearchStatus.NETWORK_ERROR,
                        elapsed_seconds=round(time.time() - t0, 2),
                        error=err_msg,
                    )
                finally:
                    browser.close()

        except Exception as e:
            err_msg = f"Unexpected Yandex visual search error: {e}"
            logger.error(err_msg, exc_info=True)
            return SearchResponse(
                provider="yandex",
                status=SearchStatus.BROWSER_ERROR,
                elapsed_seconds=round(time.time() - t0, 2),
                error=err_msg,
            )

        elapsed = round(time.time() - t0, 2)
        logger.info("Yandex search completed")
        logger.info(f"Usable candidates: {len(candidates)}")

        if candidates:
            status = SearchStatus.SUCCESS
            error = None
        elif raw_count > 0:
            status = SearchStatus.PARSER_FAILURE
            error = f"Yandex returned {raw_count} raw links, but none met candidate domain criteria."
        else:
            status = SearchStatus.NO_RESULTS
            error = "Yandex search completed, but no usable candidates were discovered."

        return SearchResponse(
            provider="yandex",
            status=status,
            elapsed_seconds=elapsed,
            raw_results_count=raw_count,
            parsed_candidates_count=len(candidates),
            candidates=candidates,
            error=error,
            diagnostics=diagnostics,
        )
