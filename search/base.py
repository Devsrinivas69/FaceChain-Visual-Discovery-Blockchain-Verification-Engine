"""Base models and abstract class for visual search providers."""

from abc import ABC, abstractmethod
from typing import List

from .models import (
    SearchCandidate,
    SearchResponse,
    SearchStatus,
    UnsupportedProviderError,
    normalize_provider,
)


class SearchProvider(ABC):
    """Abstract visual search provider interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the search provider."""
        pass

    @abstractmethod
    def search_detailed(self, image_path: str) -> SearchResponse:
        """
        Executes search and returns a structured SearchResponse with status,
        diagnostics, raw counts, and discovered candidates.
        """
        pass

    def search(self, image_path: str) -> List[SearchCandidate]:
        """
        Executes visual search and returns discovered candidate list.
        Default implementation delegates to search_detailed.
        """
        response = self.search_detailed(image_path)
        return response.candidates


__all__ = [
    "SearchCandidate",
    "SearchResponse",
    "SearchStatus",
    "UnsupportedProviderError",
    "normalize_provider",
    "SearchProvider",
]
