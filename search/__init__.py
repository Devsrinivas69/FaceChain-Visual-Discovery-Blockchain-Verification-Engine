"""Visual search provider abstraction module."""

from .base import SearchCandidate, SearchProvider
from .google_lens import GoogleLensProvider
from .bing_visual import BingVisualProvider
from .yandex_visual import YandexVisualProvider
from .auto_visual import AutoVisualProvider
from .ranking import rank_candidates, compute_composite_score


def get_search_provider(provider_name: str = "auto") -> SearchProvider:
    """Factory to retrieve configured search provider instance."""
    name_clean = provider_name.strip().lower()
    if name_clean in ("bing", "bing_visual"):
        return BingVisualProvider()
    elif name_clean in ("yandex", "yandex_visual"):
        return YandexVisualProvider()
    elif name_clean in ("google", "google_lens", "lens"):
        return GoogleLensProvider()
    elif name_clean == "auto":
        return AutoVisualProvider()
    else:
        return AutoVisualProvider()


__all__ = [
    "SearchCandidate",
    "SearchProvider",
    "GoogleLensProvider",
    "BingVisualProvider",
    "YandexVisualProvider",
    "AutoVisualProvider",
    "get_search_provider",
    "rank_candidates",
    "compute_composite_score",
]
