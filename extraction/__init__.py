"""Extraction package for URL normalization, downloads, and metadata."""

from .url_utils import normalize_url, extract_domain
from .downloader import download_candidate_image, MediaDownloadError
from .metadata import MatchedContentRecord, build_matched_record

__all__ = [
    "normalize_url",
    "extract_domain",
    "download_candidate_image",
    "MediaDownloadError",
    "MatchedContentRecord",
    "build_matched_record",
]
