"""Automated cascade visual search provider."""

import logging
import time
from typing import Any, Dict, List
from .base import SearchCandidate, SearchProvider
from .google_lens import GoogleLensProvider
from .bing_visual import BingVisualProvider
from .yandex_visual import YandexVisualProvider
from .models import SearchResponse, SearchStatus

logger = logging.getLogger(__name__)


class AutoVisualProvider(SearchProvider):
    """
    Cascades through live visual search engines:
    1. Try Google Lens
    2. If Google fails or yields 0 candidates, try Bing Visual Search
    3. If Bing fails or yields 0 candidates, try Yandex Visual Search
    If all engines fail, returns an empty list and structured failure diagnostics.
    No hardcoded, fake, or synthetic candidates are ever returned.
    """

    def __init__(self):
        self.last_provider_used = "auto"

    @property
    def name(self) -> str:
        return "auto"

    def search_detailed(self, image_path: str) -> SearchResponse:
        t0 = time.time()
        logger.info("Starting Auto Visual Search cascade (Google Lens -> Bing Visual -> Yandex Visual)...")

        cascade_providers = [
            ("google", GoogleLensProvider()),
            ("bing", BingVisualProvider()),
            ("yandex", YandexVisualProvider()),
        ]

        attempt_summaries = []
        diagnostics: Dict[str, Any] = {"attempts": {}}

        for prov_key, provider in cascade_providers:
            logger.info(f"Auto cascade attempting: {provider.name}...")
            try:
                resp = provider.search_detailed(image_path)
                diagnostics["attempts"][prov_key] = {
                    "status": resp.status.value,
                    "elapsed": resp.elapsed_seconds,
                    "raw_count": resp.raw_results_count,
                    "parsed_count": resp.parsed_candidates_count,
                    "error": resp.error,
                }
                if resp.candidates:
                    self.last_provider_used = prov_key
                    logger.info(
                        f"Auto cascade succeeded via {prov_key} with {len(resp.candidates)} live candidates."
                    )
                    resp.provider = "auto"
                    resp.diagnostics.update(diagnostics)
                    resp.diagnostics["winning_provider"] = prov_key
                    return resp

                reason = resp.error or resp.status.value
                attempt_summaries.append(f"{prov_key.capitalize()} ({reason})")

            except Exception as e:
                logger.warning(f"Auto cascade provider {prov_key} threw exception: {e}")
                diagnostics["attempts"][prov_key] = {"error": str(e)}
                attempt_summaries.append(f"{prov_key.capitalize()} (Error: {e})")

        elapsed = round(time.time() - t0, 2)
        summary_text = f"No candidates discovered. Providers attempted: {', '.join(attempt_summaries)}."
        logger.error(summary_text)

        return SearchResponse(
            provider="auto",
            status=SearchStatus.NO_RESULTS,
            elapsed_seconds=elapsed,
            raw_results_count=0,
            parsed_candidates_count=0,
            candidates=[],
            error=summary_text,
            diagnostics=diagnostics,
        )
