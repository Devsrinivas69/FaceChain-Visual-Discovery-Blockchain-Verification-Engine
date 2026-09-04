"""Yandex Visual Search provider using browser automation."""

import logging
from pathlib import Path
from typing import List
from playwright.sync_api import sync_playwright

from config import (
    SEARCH_HEADLESS,
    MAX_SEARCH_CANDIDATES,
    USER_AGENT,
)
from extraction.url_utils import extract_domain, normalize_url
from .base import SearchCandidate, SearchProvider

logger = logging.getLogger(__name__)

YANDEX_INTERNAL_DOMAINS = {
    "yandex.com",
    "yandex.ru",
    "ya.ru",
    "yastatic.net",
    "kinopoisk.ru",
    "auto.ru",
    "edadeal.ru",
}


class YandexVisualProvider(SearchProvider):
    """Executes live visual reverse-image search via Yandex Images."""

    @property
    def name(self) -> str:
        return "yandex_visual"

    def search(self, image_path: str) -> List[SearchCandidate]:
        path_obj = Path(image_path).resolve()
        if not path_obj.is_file():
            raise FileNotFoundError(f"Input image does not exist: {path_obj}")

        candidates: List[SearchCandidate] = []
        seen_urls = set()

        logger.info(f"Launching Yandex Visual Search for: {path_obj.name}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=SEARCH_HEADLESS)
            page = browser.new_page(
                viewport={"width": 1400, "height": 1000},
                user_agent=USER_AGENT,
            )

            try:
                page.goto("https://yandex.com/images", timeout=30000)
                page.wait_for_timeout(2000)

                fi = page.query_selector('input[type="file"]')
                if not fi:
                    logger.warning("Could not find file input on Yandex Images.")
                    return []

                logger.info(f"Uploading file to Yandex: {path_obj.name}")
                fi.set_input_files(str(path_obj))

                for i in range(25):
                    page.wait_for_timeout(1000)
                    if "cbir_id" in page.url or "rpt=imageview" in page.url:
                        logger.info(f"Yandex results URL reached at second {i+1}: {page.url[:80]}...")
                        break

                page.wait_for_timeout(4000)

                cards = page.evaluate("""() => {
                    const items = [];
                    for (const a of document.querySelectorAll('a[href^="http"]')) {
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

                logger.info(f"Yandex extracted {len(cards)} raw links.")

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

                logger.info(f"Yandex Visual Search discovered {len(candidates)} usable candidates.")

            except Exception as e:
                logger.error(f"Yandex Visual Search error: {e}", exc_info=True)
            finally:
                browser.close()

        return candidates
