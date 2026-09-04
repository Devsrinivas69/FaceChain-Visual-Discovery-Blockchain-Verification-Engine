"""Automated cascade visual search provider — fast parallel mode."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from .base import SearchCandidate, SearchProvider
from .google_lens import GoogleLensProvider
from .bing_visual import BingVisualProvider
from .yandex_visual import YandexVisualProvider
from .models import SearchResponse, SearchStatus

logger = logging.getLogger(__name__)

# Per-provider timeout cap (seconds). Bing is fastest so try it first.
PROVIDER_TIMEOUT_S = 20


class AutoVisualProvider(SearchProvider):
    """
    Runs all live visual search engines in parallel and returns results
    from the first engine that succeeds (most candidates wins on tie).
    Falls back to best partial result if none fully succeed.
    No hardcoded, fake, or synthetic candidates are ever returned.
    """

    def __init__(self):
        self.last_provider_used = "auto"

    @property
    def name(self) -> str:
        return "auto"

    def search_detailed(self, image_path: str) -> SearchResponse:
        t0 = time.time()
        logger.info(
            "Starting Auto Visual Search — parallel (Bing + Yandex + Google)..."
        )

        providers = [
            ("bing", BingVisualProvider()),
            ("google", GoogleLensProvider()),
            ("yandex", YandexVisualProvider()),
        ]

        attempt_summaries: List[str] = []
        diagnostics: Dict[str, Any] = {"attempts": {}, "mode": "parallel"}

        best_resp: SearchResponse | None = None
        best_count = 0

        def _run(key_prov):
            prov_key, provider = key_prov
            logger.info(f"[auto] Launching {prov_key}...")
            try:
                resp = provider.search_detailed(image_path)
                logger.info(
                    f"[auto] {prov_key} finished: {len(resp.candidates)} candidates "
                    f"in {resp.elapsed_seconds}s"
                )
                return prov_key, resp
            except Exception as e:
                logger.warning(f"[auto] {prov_key} threw exception: {e}")
                return prov_key, SearchResponse(
                    provider=prov_key,
                    status=SearchStatus.NETWORK_ERROR,
                    elapsed_seconds=round(time.time() - t0, 2),
                    error=str(e),
                )

        with ThreadPoolExecutor(max_workers=len(providers)) as executor:
            futures = {executor.submit(_run, pair): pair[0] for pair in providers}

            for future in as_completed(futures, timeout=PROVIDER_TIMEOUT_S + 5):
                prov_key, resp = future.result()
                diagnostics["attempts"][prov_key] = {
                    "status": resp.status.value,
                    "elapsed": resp.elapsed_seconds,
                    "raw_count": resp.raw_results_count,
                    "parsed_count": resp.parsed_candidates_count,
                    "error": resp.error,
                }

                if resp.candidates and len(resp.candidates) > best_count:
                    best_count = len(resp.candidates)
                    best_resp = resp
                    best_resp.provider = "auto"
                    best_resp.diagnostics.update(diagnostics)
                    best_resp.diagnostics["winning_provider"] = prov_key
                    self.last_provider_used = prov_key
                    logger.info(
                        f"[auto] New best: {prov_key} with {best_count} candidates. "
                        f"Total elapsed: {time.time()-t0:.2f}s"
                    )

                reason = resp.error or resp.status.value
                attempt_summaries.append(f"{prov_key.capitalize()} ({reason})")

                # Early-exit: if we have a solid result (≥5 candidates), stop waiting
                if best_count >= 5:
                    logger.info(
                        f"[auto] Early-exit with {best_count} candidates from "
                        f"{self.last_provider_used} at {time.time()-t0:.2f}s"
                    )
                    # Cancel remaining futures (best-effort)
                    for f in futures:
                        f.cancel()
                    break

        if best_resp is not None and best_resp.candidates:
            # Update diagnostics with final timing
            best_resp.elapsed_seconds = round(time.time() - t0, 2)
            best_resp.diagnostics.update(diagnostics)
            return best_resp

        # All providers failed
        elapsed = round(time.time() - t0, 2)
        summary_text = (
            f"No candidates discovered. Providers attempted: "
            f"{', '.join(attempt_summaries)}."
        )
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
