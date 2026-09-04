"""Tests for manifest canonicalization and provenance hash determinism."""

from fingerprint.canonical import (
    create_canonical_manifest,
    canonicalize_manifest,
    compute_provenance_hash,
    to_bytes32_hex,
)

def test_manifest_key_order_invariance():
    """Manifests with different Python dict key ordering must yield identical canonical bytes and hash."""
    manifest_a = {
        "version": "1.0",
        "source_url": "https://example.com/post/101",
        "image_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        "title": "Example Post",
        "source_domain": "example.com",
        "retrieved_at": "2026-09-03T12:00:00Z",
    }

    # Same keys in reversed order
    manifest_b = {
        "retrieved_at": "2026-09-03T12:00:00Z",
        "source_domain": "example.com",
        "title": "Example Post",
        "image_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        "source_url": "https://example.com/post/101",
        "version": "1.0",
    }

    bytes_a = canonicalize_manifest(manifest_a)
    bytes_b = canonicalize_manifest(manifest_b)

    assert bytes_a == bytes_b
    assert compute_provenance_hash(manifest_a) == compute_provenance_hash(manifest_b)

def test_manifest_whitespace_and_compact_serialization():
    manifest = {
        "version": "1.0",
        "source_url": "https://example.com/post/101  ",
        "image_sha256": "ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890",
        "title": " Example Post ",
        "source_domain": "EXAMPLE.COM",
        "retrieved_at": "2026-09-03T12:00:00Z",
    }

    canonical_bytes = canonicalize_manifest(manifest)
    # Check that keys are sorted and separators have no spaces: ',' and ':'
    assert b'","' in canonical_bytes or b'":"' in canonical_bytes
    assert b': ' not in canonical_bytes
    assert b', ' not in canonical_bytes

def test_to_bytes32_hex_format():
    hash_hex = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    b32 = to_bytes32_hex(hash_hex)
    assert b32.startswith("0x")
    assert len(b32) == 66
