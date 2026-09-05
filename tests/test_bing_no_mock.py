"""Tests ensuring BingVisualProvider produces zero mock data and drops invalid candidates."""

import pytest
from search.bing_visual import BingVisualProvider, _decode_bing_redirect


class TestBingVisualNoMockData:
    """Verifies that no mock, synthetic, or fake data is ever emitted."""

    def test_decode_bing_redirect(self):
        # Base64 encoded: "https://en.wikipedia.org/wiki/Thomas_Shelby" -> "aHR0cHM6Ly9lbi53aWtpcGVkaWEub3JnL3dpa2kvVGhvbWFzX1NoZWxieQ"
        sample_href = "https://www.bing.com/ck/a?!&&p=123&u=a1aHR0cHM6Ly9lbi53aWtpcGVkaWEub3JnL3dpa2kvVGhvbWFzX1NoZWxieQ&ntb=1"
        decoded = _decode_bing_redirect(sample_href)
        assert decoded == "https://en.wikipedia.org/wiki/Thomas_Shelby"

    def test_build_candidates_drops_missing_or_internal_urls(self):
        provider = BingVisualProvider()
        raw_items = [
            # 1. No href, only CDN thumbnail (e.g. from homepage trending images) -> MUST BE DROPPED
            {"href": "", "imgSrc": "https://th.bing.com/th/id/OIP.beach123", "title": "Beach"},
            # 2. Bing internal URL -> MUST BE DROPPED
            {"href": "https://www.bing.com/images/search?q=dogs", "imgSrc": "https://th.bing.com/th/id/OIP.dog123", "title": "Dogs"},
            # 3. Valid external URL -> MUST BE KEPT
            {"href": "https://en.wikipedia.org/wiki/Thomas_Shelby", "imgSrc": "https://th.bing.com/th/id/OIP.shelby", "title": "Thomas Shelby"},
            # 4. Obfuscated Bing redirect to real external page -> MUST BE KEPT
            {
                "href": "https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly9tYW5vZm1hbnkuY29tL3RoZS1yZWFsLXRob21hcy1zaGVsYnk&ntb=1",
                "imgSrc": "https://th.bing.com/th/id/OIP.real",
                "title": "Real Thomas Shelby"
            },
        ]

        candidates = provider._build_candidates(raw_items)

        # Must only have the 2 valid external candidates
        assert len(candidates) == 2

        # Verify no candidate has a mock domain
        for c in candidates:
            assert "web-match" not in c.source_domain
            assert "bing.com" not in c.source_domain
            assert c.url.startswith("http")

        assert candidates[0].source_domain == "en.wikipedia.org"
        assert candidates[1].source_domain == "manofmany.com"

    def test_zero_web_match_in_search_package(self):
        """Audit test: verify that web-match- does not appear in search package."""
        import subprocess
        result = subprocess.run(
            ["git", "grep", "-i", "web-match-", "--", "search/"],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", f"Found web-match- in search/: {result.stdout}"
