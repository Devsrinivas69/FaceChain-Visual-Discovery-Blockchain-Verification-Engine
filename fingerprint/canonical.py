"""Canonicalization and provenance hash generation for visual content."""

import json
from datetime import datetime, timezone
from typing import Any, Dict
from .hashing import compute_sha256

def create_canonical_manifest(
    source_url: str,
    image_sha256: str,
    title: str,
    source_domain: str,
    retrieved_at: str | None = None,
    version: str = "1.0",
) -> Dict[str, Any]:
    """
    Creates the canonical dictionary representing content provenance.
    All fields are strictly typed and normalized.
    """
    if retrieved_at is None:
        retrieved_at = datetime.now(timezone.utc).isoformat()

    return {
        "version": str(version),
        "source_url": str(source_url).strip(),
        "image_sha256": str(image_sha256).strip().lower(),
        "title": str(title).strip(),
        "source_domain": str(source_domain).strip().lower(),
        "retrieved_at": str(retrieved_at).strip(),
    }

def canonicalize_manifest(manifest: Dict[str, Any]) -> bytes:
    """
    Deterministically serializes manifest dictionary into bytes:
    - Keys sorted lexicographically
    - Compact separators (no trailing spaces: ',' and ':')
    - Unicode characters preserved (ensure_ascii=False)
    - Encoded as UTF-8
    """
    # Create normalized subset strictly keeping defined provenance fields
    normalized = {
        "version": str(manifest.get("version", "1.0")),
        "source_url": str(manifest.get("source_url", "")).strip(),
        "image_sha256": str(manifest.get("image_sha256", "")).strip().lower(),
        "title": str(manifest.get("title", "")).strip(),
        "source_domain": str(manifest.get("source_domain", "")).strip().lower(),
        "retrieved_at": str(manifest.get("retrieved_at", "")).strip(),
    }

    serialized = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return serialized.encode("utf-8")

def compute_provenance_hash(manifest_or_bytes: Dict[str, Any] | bytes) -> str:
    """
    Computes the deterministic SHA-256 provenance hash of the canonical manifest.
    Returns a 64-character lowercase hex string.
    """
    if isinstance(manifest_or_bytes, dict):
        canonical_bytes = canonicalize_manifest(manifest_or_bytes)
    elif isinstance(manifest_or_bytes, (bytes, bytearray)):
        canonical_bytes = bytes(manifest_or_bytes)
    else:
        raise TypeError("Input must be manifest dict or canonical bytes.")

    return compute_sha256(canonical_bytes)

def to_bytes32_hex(hash_str: str) -> str:
    """Ensures hash string has standard 0x prefix and is 66 characters total."""
    cleaned = hash_str.strip().lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    if len(cleaned) != 64:
        raise ValueError(f"Expected 64-char hex string, got {len(cleaned)}: {hash_str}")
    return f"0x{cleaned}"
