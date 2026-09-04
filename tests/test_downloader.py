"""Unit tests for extraction/downloader image validation."""

import io
import pytest
from PIL import Image, UnidentifiedImageError
from extraction.downloader import (
    load_valid_image_from_bytes,
    MediaDownloadError,
    CandidateDownload,
)


def test_load_valid_image_from_bytes_jpeg():
    # Create valid synthetic RGB image
    img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    valid_bytes = buf.getvalue()

    result = load_valid_image_from_bytes(valid_bytes)
    assert isinstance(result, Image.Image)
    assert result.size == (100, 100)
    assert result.mode == "RGB"


def test_load_valid_image_from_bytes_png():
    img = Image.new("RGBA", (50, 50), color=(0, 255, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    valid_bytes = buf.getvalue()

    result = load_valid_image_from_bytes(valid_bytes)
    assert isinstance(result, Image.Image)
    assert result.size == (50, 50)
    assert result.mode == "RGB"  # converted to RGB


def test_load_valid_image_from_bytes_rejects_empty():
    with pytest.raises(MediaDownloadError, match="empty or too small"):
        load_valid_image_from_bytes(b"")


def test_load_valid_image_from_bytes_rejects_html():
    html_payload = b"<!DOCTYPE html><html><head><title>403 Forbidden</title></head><body><h1>Access Denied</h1></body></html>"
    with pytest.raises(MediaDownloadError, match="HTML/JSON error document"):
        load_valid_image_from_bytes(html_payload)


def test_load_valid_image_from_bytes_rejects_corrupted():
    corrupted_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 200  # JPEG header followed by invalid data
    with pytest.raises((MediaDownloadError, UnidentifiedImageError)):
        load_valid_image_from_bytes(corrupted_bytes)


def test_candidate_download_dict_access():
    cd = CandidateDownload(
        success=True,
        resolved_url="https://example.com/photo.jpg",
        byte_size=1234,
        image_sha256="abc123def456",
    )
    assert cd["success"] is True
    assert cd["resolved_url"] == "https://example.com/photo.jpg"
    assert cd.get("byte_size") == 1234
    assert cd.get("nonexistent", "fallback") == "fallback"
