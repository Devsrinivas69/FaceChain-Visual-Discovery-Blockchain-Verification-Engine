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
        """Resize image to max 1000px and convert to optimized JPEG bytes."""
        im = Image.open(path_obj).convert("RGB")
        max_px = min(MAX_UPLOAD_PX, 1000)
        if max(im.size) > max_px:
            im.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

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
        resized_path = config.CACHE_DIR / "_bing_upload_tmp.jpg"
        resized_path.parent.mkdir(parents=True, exist_ok=True)
        resized_path.write_bytes(img_bytes)

        is_render = bool(os.getenv("RENDER") or os.getenv("SERVER_SOFTWARE"))
        use_headless = True if (is_render or os.name != "nt") else SEARCH_HEADLESS

        candidates: List[SearchCandidate] = []
        raw_count = 0
        diagnostics: Dict[str, Any] = {
            "headless": use_headless,
            "render_detected": is_render,
            "method": "visualsearch_live",
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
                    viewport={"width": 1400, "height": 1000},
                )
                page = context.new_page()

                try:
                    logger.info("Navigating to Bing Visual Search...")
                    page.goto(
                        "https://www.bing.com/visualsearch",
                        timeout=25000,
                    )
                    page.wait_for_timeout(1800)
                    self._dismiss_popups(page)

                    # Locate file input element
                    file_input = page.query_selector('input[type="file"]')
                    if not file_input:
                        for cam_sel in ["#sb_imgsearch", "#sbi_b", '[aria-label*="Visual search"]', 'label[for="sb_file_upload"]']:
                            try:
                                btn = page.query_selector(cam_sel)
                                if btn and btn.is_visible():
                                    btn.click()
                                    page.wait_for_timeout(800)
                                    break
                            except Exception:
                                pass
                        file_input = page.query_selector('input[type="file"]')

                    if not file_input:
                        return SearchResponse(
                            provider="bing",
                            status=SearchStatus.PARSER_FAILURE,
                            elapsed_seconds=round(time.time() - t0, 2),
                            error="Could not locate file input on Bing Visual Search.",
                            diagnostics=diagnostics,
                        )

                    logger.info(f"Uploading image to Bing Visual Search: {resized_path.name}")
                    file_input.set_input_files(str(resized_path))

                    # Wait for results page navigation
                    for i in range(12):
                        page.wait_for_timeout(1000)
                        curr_url = page.url
                        if "search" in curr_url and ("bcid=" in curr_url or "q=" in curr_url or "view=detailv2" in curr_url):
                            logger.info(f"Bing results reached at sec {i+1}: {curr_url[:80]}...")
                            break

                    page.wait_for_timeout(3000)

                    # Extract real visual match cards from results
                    card_data = page.evaluate("""() => {
                        const results = [];
                        const seen = new Set();
                        
                        // 1. Primary: Images with OIP thumbnails (Bing visual matches)
                        for (const img of document.querySelectorAll('img')) {
                            const src = img.src || img.getAttribute('data-src') || '';
                            if (!src || (!src.includes('th/id/OIP') && !src.includes('th?id=OIP'))) continue;
                            if (seen.has(src)) continue;
                            seen.add(src);
                            
                            const parentA = img.closest('a') || img.parentElement?.querySelector('a');
                            const card = img.closest('.iacf_item') || img.closest('.b_algo') || img.parentElement?.parentElement;
                            
                            let domain = '';
                            let title = '';
                            let extUrl = '';
                            
                            if (card) {
                                const dmEl = card.querySelector('.iacf_dm, .cite, .b_attribution, [data-domain]');
                                if (dmEl) domain = dmEl.innerText.trim();
                                const tEl = card.querySelector('h2, .title, .b_title');
                                if (tEl) title = tEl.innerText.replace(/\\n+/g, ' ').trim();
                                for (const a of card.querySelectorAll('a')) {
                                    if (a.href && !a.href.includes('bing.com') && !a.href.includes('microsoft.com')) {
                                        extUrl = a.href;
                                        break;
                                    }
                                }
                            }
                            
                            const fallbackUrl = parentA ? parentA.href : src;
                            results.push({
                                image_url: src,
                                thumbnail_url: src,
                                page_url: extUrl || fallbackUrl,
                                domain: domain,
                                title: title || 'Visual Match'
                            });
                        }
                        
                        // 2. Secondary fallback: check a[m] metadata if present
                        if (results.length === 0) {
                            for (const a of document.querySelectorAll('a[m]')) {
                                try {
                                    const meta = JSON.parse(a.getAttribute('m') || '{}');
                                    const murl = meta.murl || '';
                                    const purl = meta.purl || '';
                                    const turl = meta.turl || '';
                                    const desc = meta.t || meta.desc || '';
                                    if (murl && !seen.has(murl)) {
                                        seen.add(murl);
                                        results.push({ image_url: murl, page_url: purl, thumbnail_url: turl || murl, title: desc });
                                    }
                                } catch(e) {}
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
            item_dom  = (item.get("domain") or "").strip()

            if not image_url:
                continue

            norm = normalize_url(image_url)
            if norm in seen:
                continue
            seen.add(norm)

            # Determine source domain cleanly
            domain = ""
            if item_dom and not any(d in item_dom.lower() for d in BING_INTERNAL_DOMAINS):
                domain = item_dom
            elif page_url:
                extracted = extract_domain(page_url)
                if extracted and not any(d in extracted for d in BING_INTERNAL_DOMAINS):
                    domain = extracted

            if not domain:
                domain = f"web-match-{rank}.org"

            if not title:
                title = f"Visual match on {domain}"
            if len(title) > 120:
                title = title[:117] + "..."

            source_url = page_url if page_url and not any(d in page_url for d in BING_INTERNAL_DOMAINS) else image_url
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
