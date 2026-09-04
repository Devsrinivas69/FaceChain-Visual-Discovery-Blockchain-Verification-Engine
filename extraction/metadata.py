"""Metadata record builder for matched candidate content."""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict
from .url_utils import normalize_url, extract_domain

@dataclass
class MatchedContentRecord:
    source_url: str
    normalized_url: str
    title: str
    source_domain: str
    image_url: str
    face_similarity: float
    search_provider: str
    retrieved_at: str
    content_type: str
    image_byte_size: int
    image_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

def build_matched_record(
    source_url: str,
    title: str,
    image_url: str,
    face_similarity: float,
    search_provider: str,
    content_type: str,
    image_byte_size: int,
    image_sha256: str,
    retrieved_at: str | None = None,
) -> MatchedContentRecord:
    """Constructs an immutable-style local record for matched candidate content."""
    if retrieved_at is None:
        retrieved_at = datetime.now(timezone.utc).isoformat()

    norm_url = normalize_url(source_url)
    domain = extract_domain(source_url)
    clean_title = (title or "").strip() or f"Content from {domain}"

    return MatchedContentRecord(
        source_url=source_url,
        normalized_url=norm_url,
        title=clean_title,
        source_domain=domain,
        image_url=image_url,
        face_similarity=round(face_similarity, 4),
        search_provider=search_provider,
        retrieved_at=retrieved_at,
        content_type=content_type,
        image_byte_size=image_byte_size,
        image_sha256=image_sha256.lower(),
    )
