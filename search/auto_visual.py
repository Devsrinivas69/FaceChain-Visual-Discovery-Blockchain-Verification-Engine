"""Automated cascade visual search provider."""

import logging
from typing import List
from .base import SearchCandidate, SearchProvider
from .google_lens import GoogleLensProvider
from .bing_visual import BingVisualProvider
from .yandex_visual import YandexVisualProvider

logger = logging.getLogger(__name__)


class AutoVisualProvider(SearchProvider):
    """
    Cascades through live visual search engines:
    1. Try Google Lens
    2. If Google fails or yields 0 candidates, try Bing Visual Search
    3. If Bing fails or yields 0 candidates, try Yandex Visual Search
    If all engines fail, returns an empty list.
    No hardcoded, fake, or synthetic candidates are ever returned.
    """

    def __init__(self):
        self.last_provider_used = "auto"

    @property
    def name(self) -> str:
        return "auto"

    def search(self, image_path: str) -> List[SearchCandidate]:
        # 1. Try Google Lens
        logger.info("Auto visual search attempting Google Lens...")
        try:
            candidates = GoogleLensProvider().search(image_path)
            if candidates:
                self.last_provider_used = "google_lens"
                logger.info(f"Google Lens returned {len(candidates)} live candidates.")
                return candidates
        except Exception as e:
            logger.warning(f"Google Lens auto attempt failed: {e}")

        # 2. Try Bing Visual Search
        logger.info("Auto visual search attempting Bing Visual Search...")
        try:
            candidates = BingVisualProvider().search(image_path)
            if candidates:
                self.last_provider_used = "bing_visual"
                logger.info(f"Bing Visual returned {len(candidates)} live candidates.")
                return candidates
        except Exception as e:
            logger.warning(f"Bing Visual auto attempt failed: {e}")

        # 3. Try Yandex Visual Search
        logger.info("Auto visual search attempting Yandex Visual Search...")
        try:
            candidates = YandexVisualProvider().search(image_path)
            if candidates:
                self.last_provider_used = "yandex_visual"
                logger.info(f"Yandex Visual returned {len(candidates)} live candidates.")
                return candidates
        except Exception as e:
            logger.warning(f"Yandex Visual auto attempt failed: {e}")

        logger.error("All visual search engines in auto cascade returned 0 candidates.")
        return []
