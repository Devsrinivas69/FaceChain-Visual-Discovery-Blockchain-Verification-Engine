"""Canonical pipeline models: CandidateResult with explicit status states."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Optional


class CandidateStatus(str, Enum):
    """Exhaustive lifecycle states for a visual search candidate."""
    DISCOVERED = "DISCOVERED"          # Found by search engine, not yet downloaded
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"  # HTTP error, bot block, unreachable
    INVALID_IMAGE = "INVALID_IMAGE"    # Bytes don't decode as valid image
    NO_FACE = "NO_FACE"               # Valid image but zero human faces detected
    FACE_DETECTED = "FACE_DETECTED"   # Human face(s) found, similarity computed
    BELOW_THRESHOLD = "BELOW_THRESHOLD"  # Similarity computed but < threshold
    MATCH = "MATCH"                    # Similarity >= threshold — confirmed match
    MATCH_ERROR = "MATCH_ERROR"        # Face detected but embedding/similarity failed


@dataclass
class CandidateResult:
    """
    Canonical per-candidate result object.
    Every field is always present. No optional access patterns should fail.
    This is the SINGLE source of truth for is_match and status.
    """
    # Identity
    candidate_id: str               # e.g. "cand_01"
    source_url: str                 # Original search result URL
    source_domain: str              # Cleaned domain name
    title: str                      # Search result title
    image_url: Optional[str]        # Direct image URL if available
    thumbnail_url: Optional[str]    # Small preview URL
    search_rank: int                # Position in search results (1-indexed)
    search_provider: str            # Which engine returned this result

    # Download state
    download_success: bool = False
    local_path: Optional[str] = None
    resolved_url: Optional[str] = None
    content_type: Optional[str] = None
    byte_size: Optional[int] = None
    image_sha256: Optional[str] = None
    download_error: Optional[str] = None

    # Face analysis state
    faces_count: int = 0
    face_similarity: float = 0.0
    matched_face_index: int = -1

    # Final decision — ALWAYS present
    status: CandidateStatus = CandidateStatus.DISCOVERED
    is_match: bool = False
    rejection_reason: Optional[str] = None

    # Composite ranking
    composite_rank_score: float = 0.0

    def apply_evaluation(
        self,
        faces_count: int,
        face_similarity: float,
        matched_face_index: int,
        threshold: float,
    ) -> None:
        """
        Set face evaluation results and determine final status + is_match.
        This is the SINGLE place where is_match is assigned.
        """
        self.faces_count = faces_count
        self.matched_face_index = matched_face_index

        if not self.download_success:
            # Status already set to DOWNLOAD_FAILED or INVALID_IMAGE
            self.face_similarity = 0.0
            self.is_match = False
            return

        if faces_count == 0:
            self.status = CandidateStatus.NO_FACE
            self.face_similarity = 0.0
            self.is_match = False
            self.rejection_reason = "No human face detected in candidate image"
            return

        self.face_similarity = max(0.0, float(face_similarity))

        if self.face_similarity >= threshold:
            self.status = CandidateStatus.MATCH
            self.is_match = True
            self.rejection_reason = None
        else:
            self.status = CandidateStatus.BELOW_THRESHOLD
            self.is_match = False
            self.rejection_reason = (
                f"Face similarity {self.face_similarity:.3f} "
                f"below threshold {threshold:.2f}"
            )

    def mark_download_failed(self, error: str) -> None:
        """Mark this candidate as having a failed download."""
        self.download_success = False
        self.download_error = error
        self.status = CandidateStatus.DOWNLOAD_FAILED
        self.is_match = False
        self.rejection_reason = f"Media inaccessible: {error}"

    def mark_invalid_image(self, error: str) -> None:
        """Mark this candidate as having an invalid/undecodable image."""
        self.download_success = False
        self.download_error = error
        self.status = CandidateStatus.INVALID_IMAGE
        self.is_match = False
        self.rejection_reason = f"Invalid image data: {error}"

    def mark_match_error(self, error: str) -> None:
        """Mark this candidate as having a face embedding/comparison failure."""
        self.status = CandidateStatus.MATCH_ERROR
        self.is_match = False
        self.rejection_reason = f"Face evaluation error: {error}"

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to a plain dictionary for Streamlit session state.
        ALL keys including is_match are always present.
        """
        d = asdict(self)
        # Enum serialization: convert to string value
        d["status"] = self.status.value
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CandidateResult":
        """Reconstruct from serialized dictionary (e.g. from session state)."""
        data = dict(d)
        status_val = data.pop("status", CandidateStatus.DISCOVERED.value)
        try:
            status = CandidateStatus(status_val)
        except ValueError:
            status = CandidateStatus.DISCOVERED
        cr = CandidateResult(**data)
        cr.status = status
        return cr

    @property
    def is_accessible(self) -> bool:
        return self.download_success and self.local_path is not None

    @property
    def has_face(self) -> bool:
        return self.faces_count > 0

    @property
    def status_label(self) -> str:
        labels = {
            CandidateStatus.DISCOVERED: "⏳ Pending",
            CandidateStatus.DOWNLOAD_FAILED: "❌ Download Failed",
            CandidateStatus.INVALID_IMAGE: "❌ Invalid Image",
            CandidateStatus.NO_FACE: "❌ No Human Face Detected",
            CandidateStatus.FACE_DETECTED: "👤 Face Found",
            CandidateStatus.BELOW_THRESHOLD: "⚠️ Below Similarity Threshold",
            CandidateStatus.MATCH: "✅ MATCH",
            CandidateStatus.MATCH_ERROR: "⚠️ Evaluation Error",
        }
        return labels.get(self.status, self.status.value)


def make_candidate_id(index: int, domain: str) -> str:
    """Creates a deterministic candidate identifier."""
    return f"cand_{index:02d}_{domain[:8].replace('.', '_')}"
