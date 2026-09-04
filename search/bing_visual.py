"""Bing Visual Search provider — uses kblob API directly with Playwright fallback."""

import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from PIL import Image
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import config
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

BING_INTERNAL_DOMAINS = {
    "bing.com",
    "microsoft.com",
    "live.com",
    "msn.com",
    "microsofttranslator.com",
    "bingplaces.com",
}

MAX_UPLOAD_PX = 1200

BING_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.bing.com/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.bing.com",
}

CHROMIUM_SERVER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
]


class BingVisualProvider(SearchProvider):
    """Executes live visual reverse-image search via Bing kblob API or Playwright."""

    @property
    def name(self) -> str:
        return "bing"

    def _prepare_image(self, path_obj: Path) -> bytes:
        """Resize image to max 1200px and convert to JPEG bytes."""
        im = Image.open(path_obj).convert("RGB")
        if max(im.size) > MAX_UPLOAD_PX:
            im.thumbnail((MAX_UPLOAD_PX, MAX_UPLOAD_PX), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    def _upload_to_kblob(self, img_bytes: bytes) -> Optional[str]:
        """Upload image to Bing kblob and return the visual search URL."""
        try:
            r = requests.post(
                "https://www.bing.com/images/search",
                params={
                    "q": "imgbasesearch",
                    "view": "detailv2",
                    "iss": "sbiupload",
                    "FORM": "SBIMUP",
                    "sbisrc": "ImgDropper",
                    "idpbck": "1",
                },
                files={"imgurl": ("image.jpg", img_bytes, "image/jpeg")},
                headers=BING_HEADERS,
                timeout=30,
                allow_redirects=True,
            )
            if "bingvisualsearchapi" in r.url or "visuals" in r.url or r.status_code == 200:
                return r.url
            return None
        except Exception as e:
            logger.warning(f"Bing kblob upload error: {e}")
            return None

    def search_detailed(self, image_path: str) -> SearchResponse:
        t0 = time.time()
        logger.info("SELECTED PROVIDER: bing")
        logger.info("NORMALIZED PROVIDER: bing")
        logger.info("PROVIDER IMPLEMENTATION: BingVisualProvider")

        path_obj = Path(image_path).resolve()
        if not path_obj.is_file():
            err_msg = f"Input image does not exist: {path_obj}"
            return SearchResponse(
                provider="bing",
                status=SearchStatus.UNAVAILABLE,
                elapsed_seconds=round(time.time() - t0, 2),
                error=err_msg,
            )

        img_bytes = self._prepare_image(path_obj)
        diagnostics: Dict[str, Any] = {"method": "kblob"}

        # 1. Try direct HTTP API upload first
        results_url = self._upload_to_kblob(img_bytes)
        if results_url and "bing.com" in results_url:
            try:
                r = requests.get(results_url, headers=BING_HEADERS, timeout=20)
                card_data = self._parse_html_cards(r.text)
                if card_data:
                    candidates = self._build_candidates(card_data)
                    elapsed = round(time.time() - t0, 2)
                    return SearchResponse(
                        provider="bing",
                        status=SearchStatus.SUCCESS if candidates else SearchStatus.NO_RESULTS,
                        elapsed_seconds=elapsed,
                        raw_results_count=len(card_data),
                        parsed_candidates_count=len(candidates),
                        candidates=candidates,
                        diagnostics={"method": "http_api"},
                    )
            except Exception as e:
                logger.warning(f"Direct HTML parse failed: {e}, falling back to Playwright")

        # 2. Fallback: Playwright browser automation
        diagnostics["method"] = "playwright"
        return self._playwright_search_detailed(path_obj, img_bytes, t0, diagnostics)

    def _playwright_search_detailed(
        self, path_obj: Path, img_bytes: bytes, t0: float, diagnostics: Dict[str, Any]
    ) -> SearchResponse:
        resized_path = config.CACHE_DIR / "_bing_upload_tmp.jpg"
        resized_path.parent.mkdir(parents=True, exist_ok=True)
        resized_path.write_bytes(img_bytes)

        is_render = bool(os.getenv("RENDER") or os.getenv("SERVER_SOFTWARE"))
        use_headless = True if (is_render or os.name != "nt") else SEARCH_HEADLESS

        candidates: List[SearchCandidate] = []
        raw_count = 0

        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(
                        headless=use_headless,
                        args=CHROMIUM_SERVER_ARGS,
                    )
                except Exception as b_err:
                    err = f"Failed to launch Chromium for Bing: {b_err}"
                    return SearchResponse(
                        provider="bing",
                        status=SearchStatus.BROWSER_ERROR,
                        elapsed_seconds=round(time.time() - t0, 2),
                        error=err,
                        diagnostics=diagnostics,
                    )

                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1400, "height": 1000},
                )
                page = context.new_page()

                try:
                    logger.info("Navigating to Bing Images...")
                    page.goto(
                        "https://www.bing.com/images",
                        timeout=SEARCH_TIMEOUT_MS,
                        wait_until="domcontentloaded",
                    )
                    page.wait_for_timeout(2000)
                    self._dismiss_popups(page)

                    cam_selectors = [
                        "#sb_imgsearch",
                        "#sbi_b",
                        '[aria-label*="search using an image"]',
                        '[aria-label*="Visual search"]',
                        'label[for="sb_file_upload"]',
                    ]
                    for sel in cam_selectors:
                        try:
                            btn = page.query_selector(sel)
                            if btn and btn.is_visible():
                                btn.click()
                                page.wait_for_timeout(1500)
                                break
                        except Exception:
                            pass

                    file_input = page.query_selector('input[type="file"]')
                    if not file_input:
                        return SearchResponse(
                            provider="bing",
                            status=SearchStatus.PARSER_FAILURE,
                            elapsed_seconds=round(time.time() - t0, 2),
                            error="Could not locate file input on Bing Images.",
                            diagnostics=diagnostics,
                        )

                    logger.info(f"Uploading resized image to Bing: {resized_path.name}")
                    file_input.set_input_files(str(resized_path))

                    page.wait_for_timeout(5000)
                    for result_sel in ["a.iusc", ".iuscp", ".infnmpt", "a[m]"]:
                        try:
                            page.wait_for_selector(result_sel, timeout=8000)
                            break
                        except PlaywrightTimeoutError:
                            pass

                    page.wait_for_timeout(2000)

                    card_data = page.evaluate("""() => {
                        const results = [];
                        for (const a of document.querySelectorAll('a[m]')) {
                            try {
                                const meta = JSON.parse(a.getAttribute('m') || '{}');
                                const murl  = meta.murl  || '';
                                const purl  = meta.purl  || '';
                                const turl  = meta.turl  || '';
                                const desc  = meta.t || meta.desc || '';
                                if (murl) {
                                    results.push({ image_url: murl, page_url: purl, thumbnail_url: turl, title: desc });
                                }
                            } catch(e) {}
                        }
                        if (results.length === 0) {
                            for (const img of document.querySelectorAll('img.mimg, img[src*="th?id"]')) {
                                const src = img.src || img.getAttribute('data-src') || '';
                                if (!src) continue;
                                const a = img.closest('a') || img.parentElement?.querySelector('a');
                                const href = a ? a.href : '';
                                results.push({ image_url: src, page_url: href, thumbnail_url: src, title: img.alt || '' });
                            }
                        }
                        return results;
                    }""")

                    raw_count = len(card_data)
                    candidates = self._build_candidates(card_data)

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

    def _parse_html_cards(self, html: str) -> list:
        cards = []
        for m in re.finditer(r'"murl"\s*:\s*"([^"]+)".*?"purl"\s*:\s*"([^"]*)"', html):
            murl = m.group(1).replace("\\u0026", "&")
            purl = m.group(2).replace("\\u0026", "&")
            if murl:
                cards.append({"image_url": murl, "page_url": purl, "thumbnail_url": murl, "title": ""})
        return cards

    def _build_candidates(self, card_data: list) -> List[SearchCandidate]:
        candidates = []
        seen = set()
        rank = 1
        for item in card_data:
            image_url = (item.get("image_url") or "").strip()
            page_url  = (item.get("page_url")  or "").strip()
            thumb_url = (item.get("thumbnail_url") or image_url).strip()
            title     = (item.get("title") or "").strip()

            if not image_url:
                continue

            norm = normalize_url(image_url)
            if norm in seen:
                continue
            seen.add(norm)

            domain = extract_domain(page_url) if page_url else extract_domain(image_url)
            if not domain or any(d in domain for d in BING_INTERNAL_DOMAINS):
                continue

            if not title:
                title = f"Visual match on {domain}"
            if len(title) > 120:
                title = title[:117] + "..."

            source_url = page_url or image_url
            candidates.append(
                SearchCandidate(
                    url=source_url,
                    title=title,
                    source_domain=domain,
                    search_rank=rank,
                    thumbnail_url=thumb_url,
                    image_url=image_url,
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
                    page.wait_for_timeout(800)
                    break
            except Exception:
                pass
