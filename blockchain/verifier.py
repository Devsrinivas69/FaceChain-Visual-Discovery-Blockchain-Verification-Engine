"""Cryptographic verification and tamper demonstration logic."""

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any
from PIL import Image

from fingerprint.canonical import (
    create_canonical_manifest,
    compute_provenance_hash,
    to_bytes32_hex,
)
from fingerprint.hashing import compute_image_sha256
from .client import BlockchainClient, BlockchainError

class VerificationResult:
    def __init__(
        self,
        is_verified: bool,
        local_hash: str,
        on_chain_exists: bool,
        details: Dict[str, Any],
        message: str,
    ):
        self.is_verified = is_verified
        self.local_hash = local_hash
        self.on_chain_exists = on_chain_exists
        self.details = details
        self.message = message

def verify_content(
    manifest: Dict[str, Any],
    blockchain_client: BlockchainClient,
) -> VerificationResult:
    """
    Recomputes the canonical provenance hash from manifest
    and compares it directly against the on-chain smart contract record.
    """
    recomputed_hash = compute_provenance_hash(manifest)
    formatted_hash = to_bytes32_hex(recomputed_hash)

    on_chain = blockchain_client.verify_provenance(recomputed_hash)
    exists = on_chain.get("exists", False)

    if exists:
        return VerificationResult(
            is_verified=True,
            local_hash=formatted_hash,
            on_chain_exists=True,
            details=on_chain,
            message="PROVENANCE VERIFIED: Canonical fingerprint matches on-chain cryptographic anchor.",
        )
    else:
        return VerificationResult(
            is_verified=False,
            local_hash=formatted_hash,
            on_chain_exists=False,
            details=on_chain,
            message="VERIFICATION FAILED: Fingerprint not found in the blockchain registry.",
        )

def run_tamper_demonstration(
    original_image_path: Path,
    original_manifest: Dict[str, Any],
    blockchain_client: BlockchainClient,
) -> Dict[str, Any]:
    """
    Simulates content tampering:
    1. Copies the original image.
    2. Subtly alters pixel data (e.g. flipping 3 pixels).
    3. Recomputes the image SHA-256 digest.
    4. Reconstructs the canonical manifest and computes the altered provenance hash.
    5. Queries the blockchain for this altered hash.
    6. Verifies that the cryptographic anchor fails (genuine mismatch).
    """
    orig_path = Path(original_image_path)
    tampered_path = orig_path.parent / f"tampered_{orig_path.name}"

    # Copy original to tampered file
    shutil.copyfile(orig_path, tampered_path)

    # Modify image pixels using Pillow
    with Image.open(tampered_path) as img:
        img_rgb = img.convert("RGB")
        pixels = img_rgb.load()
        width, height = img_rgb.size

        # Invert color values of 3 corner pixels
        for x, y in [(0, 0), (1, 0), (0, 1)]:
            if x < width and y < height:
                r, g, b = pixels[x, y]
                pixels[x, y] = (255 - r, 255 - g, 255 - b)

        img_rgb.save(tampered_path, format="JPEG", quality=95)

    # Recalculate image SHA-256
    tampered_img_sha256 = compute_image_sha256(tampered_path)

    # Reconstruct manifest with tampered image SHA
    tampered_manifest = dict(original_manifest)
    tampered_manifest["image_sha256"] = tampered_img_sha256

    # Recompute provenance hash
    tampered_provenance_hash = compute_provenance_hash(tampered_manifest)
    formatted_tampered_hash = to_bytes32_hex(tampered_provenance_hash)
    original_provenance_hash = to_bytes32_hex(compute_provenance_hash(original_manifest))

    # Query blockchain for tampered hash
    verification = blockchain_client.verify_provenance(tampered_provenance_hash)
    exists = verification.get("exists", False)

    return {
        "tampered_image_path": tampered_path,
        "original_image_sha256": original_manifest.get("image_sha256"),
        "tampered_image_sha256": tampered_img_sha256,
        "original_provenance_hash": original_provenance_hash,
        "tampered_provenance_hash": formatted_tampered_hash,
        "on_chain_found": exists,
        "tamper_detected": not exists,
        "status": "TAMPER DETECTED" if not exists else "UNEXPECTED_COLLISION",
    }
