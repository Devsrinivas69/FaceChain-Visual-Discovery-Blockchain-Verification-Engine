"""Visual search provider abstraction module."""

from typing import Dict, Type

from .base import (
    SearchCandidate,
    SearchProvider,
    SearchResponse,
    SearchStatus,
    UnsupportedProviderError,
    normalize_provider,
)
from .google_lens import GoogleLensProvider
from .bing_visual import BingVisualProvider
from .yandex_visual import YandexVisualProvider
from .auto_visual import AutoVisualProvider
from .ranking import rank_candidates, compute_composite_score

PROVIDERS: Dict[str, Type[SearchProvider]] = {
    "auto": AutoVisualProvider,
    "yandex": YandexVisualProvider,
    "bing": BingVisualProvider,
    "google": GoogleLensProvider,
}


def get_search_provider(provider_name: str = "auto") -> SearchProvider:
    """Factory to retrieve configured search provider instance using canonical normalization."""
    clean_name = normalize_provider(provider_name)
    provider_cls = PROVIDERS[clean_name]
    return provider_cls()


__all__ = [
    "SearchCandidate",
    "SearchProvider",
    "SearchResponse",
    "SearchStatus",
    "UnsupportedProviderError",
    "normalize_provider",
    "GoogleLensProvider",
    "BingVisualProvider",
    "YandexVisualProvider",
    "AutoVisualProvider",
    "PROVIDERS",
    "get_search_provider",
    "rank_candidates",
    "compute_composite_score",
]
