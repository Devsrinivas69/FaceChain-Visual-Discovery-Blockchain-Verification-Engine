"""Tests for URL normalization and domain extraction."""

from extraction.url_utils import normalize_url, extract_domain

def test_normalize_url_strips_tracking_parameters():
    url = "https://www.instagram.com/p/C12345/?utm_source=ig_web_copy_link&igshid=MzRlODBiNWFlZA==&theme=dark"
    norm = normalize_url(url)
    assert "utm_source" not in norm
    assert "igshid" not in norm
    assert "theme=dark" in norm

def test_normalize_url_sorts_query_parameters():
    url1 = "https://example.com/item?z=9&a=1&m=5"
    url2 = "https://example.com/item?a=1&m=5&z=9"
    assert normalize_url(url1) == normalize_url(url2)

def test_normalize_url_standardizes_slashes_and_case():
    url = "HTTP://EXAMPLE.COM:80/path/to/page/"
    norm = normalize_url(url)
    assert norm == "http://example.com/path/to/page"

def test_extract_domain():
    assert extract_domain("https://www.instagram.com/user/profile") == "instagram.com"
    assert extract_domain("http://blog.news.co.uk:8080/article") == "blog.news.co.uk"
