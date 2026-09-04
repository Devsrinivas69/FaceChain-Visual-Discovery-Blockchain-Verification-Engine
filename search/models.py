"""Models, enums, and normalization for the visual search system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SearchStatus(str, Enum):
    """Execution status of a visual search operation."""
    SUCCESS = "SUCCESS"
    NO_RESULTS = "NO_RESULTS"
    PARSER_FAILURE = "PARSER_FAILURE"
    PROVIDER_BLOCKED = "PROVIDER_BLOCKED"
    NETWORK_ERROR = "NETWORK_ERROR"
    BROWSER_ERROR = "BROWSER_ERROR"
    UNAVAILABLE = "UNAVAILABLE"


class UnsupportedProviderError(ValueError):
    """Raised when an unrecognized search provider name is requested."""
    pass


@dataclass
class SearchCandidate:
    """Discovered image candidate from visual search engine."""
    url: str
    title: str
    source_domain: str
    search_rank: int
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None

    def __post_init__(self):
        self.url = self.url.strip()
        self.title = self.title.strip()
        self.source_domain = self.source_domain.strip().lower()


@dataclass
class SearchResponse:
    """Structured response from a search provider execution."""
    provider: str
    status: SearchStatus
    elapsed_seconds: float = 0.0
    raw_results_count: int = 0
    parsed_candidates_count: int = 0
    candidates: List[SearchCandidate] = field(default_factory=list)
    error: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)


SUPPORTED_PROVIDERS = ("auto", "yandex", "bing", "google")

PROVIDER_ALIASES = {
    "yandex": "yandex",
    "yandex_visual": "yandex",
    "yandex_images": "yandex",
    "bing": "bing",
    "bing_visual": "bing",
    "google": "google",
    "google_lens": "google",
    "lens": "google",
    "auto": "auto",
    "cascade": "auto",
}


def normalize_provider(value: Any) -> str:
    """
    Canonical provider name normalizer.
    Strips whitespace, converts to lowercase, and resolves standard aliases.
    Raises UnsupportedProviderError if unrecognized.
    """
    if value is None:
        return "auto"
    cleaned = str(value).strip().lower()
    if cleaned in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[cleaned]
    raise UnsupportedProviderError(
        f"Unsupported search provider '{value}'. Supported providers are: {', '.join(SUPPORTED_PROVIDERS)}"
    )
