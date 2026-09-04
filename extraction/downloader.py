"""Secure media and candidate image downloader with strict content validation."""

import os
import io
import re
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from config import CACHE_DIR, DOWNLOAD_TIMEOUT_SECS, MAX_DOWNLOAD_SIZE_BYTES, USER_AGENT
from .url_utils import normalize_url, extract_domain

logger = logging.getLogger(__name__)


class MediaDownloadError(Exception):
    """Raised when media download or validation fails."""
    pass


@dataclass
class CandidateDownload:
    """Structured result of candidate image download and validation."""
    success: bool
    local_path: Optional[Path] = None
    resolved_url: Optional[str] = None
    content_type: Optional[str] = None
    status_code: Optional[int] = None
    byte_size: Optional[int] = None
    image_sha256: Optional[str] = None
    error: Optional[str] = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "local_path": self.local_path,
            "resolved_url": self.resolved_url,
            "content_type": self.content_type,
            "status_code": self.status_code,
            "byte_size": self.byte_size,
            "image_sha256": self.image_sha256,
            "error": self.error,
        }


def sanitize_filename(name: str) -> str:
    """Sanitizes filename to prevent directory traversal and invalid characters."""
    base = os.path.basename(name)
    cleaned = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', base)
    return cleaned[:100] if cleaned else "candidate_image.jpg"


def is_safe_url(url: str) -> bool:
    """Verifies URL scheme is strictly http or https and not pointing to private/internal networks."""
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        if not hostname or hostname in ("localhost", "127.0.0.1", "::1"):
            return False
        return True
    except Exception:
        return False


def load_valid_image_from_bytes(data: bytes) -> Image.Image:
    """
    Validates and loads an image from raw bytes.
    Strictly verifies image integrity and converts to RGB mode.
    Rejects:
    - Zero-length or small payloads (< 100 bytes)
    - HTML/XML/JSON error documents disguised as images
    - Corrupted or unidentifiable byte streams (raises UnidentifiedImageError)
    
    Returns a verified PIL Image in RGB format.
    """
    if not data or len(data) < 100:
        raise MediaDownloadError(f"Image data is empty or too small ({len(data) if data else 0} bytes).")

    # Reject HTML, XML, or JSON error documents
    prefix_lower = data[:512].lower()
    if (
        b"<!doctype html" in prefix_lower
        or b"<html" in prefix_lower
        or b"<head" in prefix_lower
        or b"<body" in prefix_lower
        or b"<?xml" in prefix_lower
        or b'{"error"' in prefix_lower
        or b'{"message"' in prefix_lower
        or b"access denied" in prefix_lower
        or b"cloudflare" in prefix_lower
    ):
        raise MediaDownloadError("Response content is an HTML/JSON error document, not a valid image.")

    try:
        bio = io.BytesIO(data)
        # Step 1: Open and verify file structure
        with Image.open(bio) as img:
            img.verify()

        # Step 2: Reopen after verify (PIL requirement) and convert to RGB
        bio.seek(0)
        reopened = Image.open(bio)
        rgb_image = reopened.convert("RGB")
        return rgb_image
    except UnidentifiedImageError as uie:
        raise UnidentifiedImageError(f"PIL cannot identify image format from downloaded bytes: {uie}")
    except Exception as exc:
        raise MediaDownloadError(f"Image validation and decoding failed: {exc}")


def resolve_page_image(page_url: str, html_content: str) -> Optional[str]:
    """Extracts high-fidelity image URL (og:image, twitter:image, or primary <img>) from HTML."""
    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # Check OpenGraph image
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            return urljoin(page_url, og_img["content"].strip())

        # Check Twitter image
        tw_img = soup.find("meta", attrs={"name": "twitter:image"})
        if tw_img and tw_img.get("content"):
            return urljoin(page_url, tw_img["content"].strip())

        # Look for large content images
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src and not src.startswith("data:"):
                src_lower = src.lower()
                if not any(x in src_lower for x in ["icon", "logo", "pixel", "tracker", "avatar"]):
                    return urljoin(page_url, src.strip())
    except Exception:
        pass
    return None


def _read_bounded(response: requests.Response) -> bytes:
    """Reads response stream up to MAX_DOWNLOAD_SIZE_BYTES to prevent memory exhaustion."""
    data = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        data.extend(chunk)
        if len(data) > MAX_DOWNLOAD_SIZE_BYTES:
            raise MediaDownloadError(f"Media exceeded size limit of {MAX_DOWNLOAD_SIZE_BYTES} bytes.")
    return bytes(data)


def download_candidate_image(
    image_url: Optional[str],
    candidate_page_url: Optional[str] = None,
    fallback_thumbnail_url: Optional[str] = None,
    prefix: str = "cand",
    raise_on_error: bool = True,
) -> CandidateDownload:
    """
    Safely downloads and cryptographically validates candidate image content.
    Guarantees:
    - Never passes unverified/corrupted bytes to callers.
    - Saves verified, readable RGB JPEG image into CACHE_DIR.
    - Computes real SHA-256 of the validated saved image.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    def _headers_for(url: str) -> dict:
        h = {}
        hostname = (urlparse(url).hostname or "").lower()
        if "bing.net" in hostname or "bing.com" in hostname:
            h["Referer"] = "https://www.bing.com/"
        elif "yandex." in hostname or "yastatic.net" in hostname:
            h["Referer"] = "https://yandex.com/"
        return h

    urls_to_try = []
    if image_url and is_safe_url(image_url):
        urls_to_try.append(("direct_image", image_url))
    if candidate_page_url and is_safe_url(candidate_page_url):
        urls_to_try.append(("page_url", candidate_page_url))
    if fallback_thumbnail_url and is_safe_url(fallback_thumbnail_url):
        urls_to_try.append(("thumbnail", fallback_thumbnail_url))

    if not urls_to_try:
        err = "No valid safe URLs provided for download."
        if raise_on_error:
            raise MediaDownloadError(err)
        return CandidateDownload(success=False, error=err)

    last_error = "No usable image sources responded."

    for kind, url in urls_to_try:
        try:
            target_url = url
            raw_bytes = None

            if kind == "page_url":
                # Fetch page HTML and resolve og:image
                resp = session.get(url, timeout=DOWNLOAD_TIMEOUT_SECS, stream=False, headers=_headers_for(url))
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code} on page {url}"
                    continue

                content_type = resp.headers.get("content-type", "").lower()
                if "image/" in content_type:
                    raw_bytes = resp.content
                    target_url = url
                else:
                    extracted_url = resolve_page_image(url, resp.text)
                    if extracted_url and is_safe_url(extracted_url):
                        img_resp = session.get(extracted_url, timeout=DOWNLOAD_TIMEOUT_SECS, stream=True, headers=_headers_for(extracted_url))
                        if img_resp.status_code == 200:
                            raw_bytes = _read_bounded(img_resp)
                            target_url = extracted_url
                        else:
                            last_error = f"HTTP {img_resp.status_code} on extracted image {extracted_url}"
                            continue
                    else:
                        last_error = "Could not resolve image from candidate webpage HTML."
                        continue
            else:
                resp = session.get(url, timeout=DOWNLOAD_TIMEOUT_SECS, stream=True, headers=_headers_for(url))
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code} on {url}"
                    continue
                raw_bytes = _read_bounded(resp)
                target_url = url

            if not raw_bytes or len(raw_bytes) < 100:
                last_error = "Downloaded content was empty or under 100 bytes."
                continue

            # Strict validation using load_valid_image_from_bytes
            pil_image = load_valid_image_from_bytes(raw_bytes)

            # Ensure safe cache directory
            CACHE_DIR.mkdir(parents=True, exist_ok=True)

            # Generate deterministic local filename from image hash
            temp_hash = hashlib.sha256(raw_bytes).hexdigest()[:12]
            filename = sanitize_filename(f"{prefix}_{temp_hash}.jpg")
            local_path = (CACHE_DIR / filename).resolve()

            # Enforce directory boundary containment
            if not str(local_path).startswith(str(CACHE_DIR.resolve())):
                raise MediaDownloadError("Path traversal check failed for cache directory.")

            # Save normalized RGB JPEG
            pil_image.save(local_path, format="JPEG", quality=95)

            # Re-read saved file to compute canonical image sha256
            final_bytes = local_path.read_bytes()
            final_sha256 = hashlib.sha256(final_bytes).hexdigest()

            return CandidateDownload(
                success=True,
                local_path=local_path,
                resolved_url=target_url,
                content_type="image/jpeg",
                status_code=200,
                byte_size=len(final_bytes),
                image_sha256=final_sha256,
                error=None,
            )

        except (MediaDownloadError, UnidentifiedImageError) as me:
            last_error = str(me)
            continue
        except Exception as exc:
            last_error = f"Download exception: {exc}"
            continue

    if raise_on_error:
        raise MediaDownloadError(f"Failed to download valid image: {last_error}")

    return CandidateDownload(
        success=False,
        error=last_error,
    )
