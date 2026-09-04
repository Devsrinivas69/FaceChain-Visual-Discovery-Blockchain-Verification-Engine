"""Cryptographic hashing utilities for media and manifests."""

import hashlib
from pathlib import Path
from typing import Union

def compute_sha256(data: bytes) -> str:
    """Computes the lowercase hexadecimal SHA-256 digest of raw bytes."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("Expected bytes or bytearray for SHA-256 calculation.")
    return hashlib.sha256(data).hexdigest()

def compute_image_sha256(image_input: Union[bytes, bytearray, str, Path]) -> str:
    """
    Computes SHA-256 digest of image bytes or image file on disk.
    Ensures bit-exact hash calculation.
    """
    if isinstance(image_input, (str, Path)):
        file_path = Path(image_input)
        if not file_path.is_file():
            raise FileNotFoundError(f"Image file not found: {file_path}")
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    elif isinstance(image_input, (bytes, bytearray)):
        return hashlib.sha256(image_input).hexdigest()
    else:
        raise TypeError(f"Unsupported image_input type: {type(image_input)}")

def hash_file(file_path: Union[str, Path], chunk_size: int = 65536) -> str:
    """Computes SHA-256 of large file using chunked streaming."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
