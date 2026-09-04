"""Tests for tamper detection behavior."""

import tempfile
from pathlib import Path
from PIL import Image
from fingerprint.hashing import compute_image_sha256
from fingerprint.canonical import create_canonical_manifest, compute_provenance_hash

def test_single_pixel_change_alters_both_hashes():
    # Create test image
    with tempfile.TemporaryDirectory() as tmp_dir:
        orig_path = Path(tmp_dir) / "original.png"
        tampered_path = Path(tmp_dir) / "tampered.png"

        img = Image.new("RGB", (64, 64), color=(120, 150, 180))
        img.save(orig_path, format="PNG")

        # Create tampered copy with one altered pixel
        img_tampered = Image.open(orig_path)
        pixels = img_tampered.load()
        pixels[0, 0] = (255, 0, 0)
        img_tampered.save(tampered_path, format="PNG")

        orig_img_hash = compute_image_sha256(orig_path)
        tampered_img_hash = compute_image_sha256(tampered_path)

        assert orig_img_hash != tampered_img_hash

        # Create manifests
        manifest_orig = create_canonical_manifest(
            source_url="https://example.com/photo.png",
            image_sha256=orig_img_hash,
            title="Photo",
            source_domain="example.com",
            retrieved_at="2026-09-03T12:00:00Z",
        )
        manifest_tampered = create_canonical_manifest(
            source_url="https://example.com/photo.png",
            image_sha256=tampered_img_hash,
            title="Photo",
            source_domain="example.com",
            retrieved_at="2026-09-03T12:00:00Z",
        )

        orig_prov_hash = compute_provenance_hash(manifest_orig)
        tampered_prov_hash = compute_provenance_hash(manifest_tampered)

        assert orig_prov_hash != tampered_prov_hash
