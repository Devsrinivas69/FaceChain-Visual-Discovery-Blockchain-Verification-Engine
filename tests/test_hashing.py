"""Tests for cryptographic hashing."""

import hashlib
import tempfile
from pathlib import Path
from fingerprint.hashing import compute_sha256, compute_image_sha256, hash_file

def test_compute_sha256_exactness():
    data = b"FaceChain Hackathon Goa 2026"
    expected = hashlib.sha256(data).hexdigest()
    assert compute_sha256(data) == expected
    assert len(compute_sha256(data)) == 64

def test_compute_sha256_different_inputs():
    hash1 = compute_sha256(b"image_content_A")
    hash2 = compute_sha256(b"image_content_B")
    assert hash1 != hash2

def test_compute_image_sha256_from_file():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(b"simulated_image_binary_data_12345")
        tmp_path = Path(tmp.name)

    try:
        file_hash = compute_image_sha256(tmp_path)
        bytes_hash = compute_sha256(b"simulated_image_binary_data_12345")
        assert file_hash == bytes_hash
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
