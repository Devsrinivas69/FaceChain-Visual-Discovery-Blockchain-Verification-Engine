"""Multi-criteria ranking and filtering for discovered face search candidates."""

from dataclasses import dataclass
from typing import List, Optional
from extraction.url_utils import extract_domain
from config import FACE_MATCH_THRESHOLD

# Reputable/prominent social and public domains to prioritize slightly when ties occur
PRIORITY_DOMAINS = {
    "instagram.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "reddit.com",
    "youtube.com",
    "pinterest.com",
    "flickr.com",
    "medium.com",
    "wikipedia.org",
    "wikimedia.org",
    "github.com",
}

@dataclass
class ScoredCandidate:
    candidate: any
    face_similarity: float
    has_accessible_image: bool
    composite_rank_score: float
    is_match: bool

def compute_composite_score(
    face_similarity: float,
    search_rank: int,
    domain: str,
    has_accessible_image: bool,
) -> float:
    """
    Computes a transparent composite ranking score.
    Face similarity is the primary driver (80% weight).
    Search rank, domain recognizability, and image accessibility serve as tie-breakers.
    """
    # Base similarity weight: 80 points max
    sim_component = face_similarity * 80.0

    # Search rank weight: up to 10 points (lower rank index = better)
    rank_component = max(0.0, 10.0 - (search_rank * 0.5))

    # Accessible image weight: 5 points
    media_component = 5.0 if has_accessible_image else 0.0

    # Domain recognizability: 5 points
    domain_clean = domain.lower()
    domain_component = 5.0 if any(p in domain_clean for p in PRIORITY_DOMAINS) else 2.0

    return sim_component + rank_component + media_component + domain_component

def rank_candidates(
    evaluated_candidates: List[dict],
    threshold: float = FACE_MATCH_THRESHOLD,
) -> List[dict]:
    """
    Ranks evaluated candidates by face similarity descending,
    filtered against the configurable FACE_MATCH_THRESHOLD.
    """
    scored = []
    for item in evaluated_candidates:
        cand = item["candidate"]
        sim = float(item.get("face_similarity", 0.0))
        has_media = bool(item.get("download_success", False))
        domain = cand.source_domain or extract_domain(cand.url)

        composite = compute_composite_score(
            face_similarity=sim,
            search_rank=cand.search_rank,
            domain=domain,
            has_accessible_image=has_media,
        )

        item_scored = dict(item)
        item_scored["composite_rank_score"] = round(composite, 2)
        item_scored["is_match"] = sim >= threshold
        scored.append(item_scored)

    # Sort strictly by face similarity descending as required, then composite
    scored.sort(key=lambda x: (x.get("face_similarity", 0.0), x["composite_rank_score"]), reverse=True)
    return scored
