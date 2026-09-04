"""Base models and abstract class for visual search providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class SearchCandidate:
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

class SearchProvider(ABC):
    """Abstract visual search provider interface."""

    @abstractmethod
    def search(self, image_path: str) -> List[SearchCandidate]:
        """
        Executes a genuine external visual search using the provided input image.
        Returns a list of discovered candidates.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the search provider."""
        pass
