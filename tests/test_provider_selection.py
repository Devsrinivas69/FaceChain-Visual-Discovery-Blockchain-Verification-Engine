"""Tests for provider selection, normalization, factory dispatch, and SearchResponse contracts."""

import pytest
from search.models import (
    SearchCandidate,
    SearchResponse,
    SearchStatus,
    UnsupportedProviderError,
    normalize_provider,
    SUPPORTED_PROVIDERS,
)
from search import (
    get_search_provider,
    YandexVisualProvider,
    BingVisualProvider,
    GoogleLensProvider,
    AutoVisualProvider,
    PROVIDERS,
)


class TestProviderNormalization:
    """Validates canonical provider normalization across case, whitespace, and aliases."""

    def test_normalize_yandex_variants(self):
        variants = ["yandex", "Yandex", " YANDEX ", "yandex_visual", "YANDEX_VISUAL", "yandex_images"]
        for v in variants:
            assert normalize_provider(v) == "yandex"

    def test_normalize_bing_variants(self):
        variants = ["bing", "Bing", "  BING  ", "bing_visual", "Bing_Visual"]
        for v in variants:
            assert normalize_provider(v) == "bing"

    def test_normalize_google_variants(self):
        variants = ["google", "Google", "google_lens", "GOOGLE_LENS", "lens", "  Lens "]
        for v in variants:
            assert normalize_provider(v) == "google"

    def test_normalize_auto_variants(self):
        variants = ["auto", "Auto", " AUTO ", "cascade", None]
        for v in variants:
            assert normalize_provider(v) == "auto"

    def test_invalid_provider_raises_clean_error(self):
        with pytest.raises(UnsupportedProviderError) as exc_info:
            normalize_provider("duckduckgo")
        assert "Unsupported search provider 'duckduckgo'" in str(exc_info.value)
        assert "Supported providers are" in str(exc_info.value)

    def test_empty_string_raises_error(self):
        with pytest.raises(UnsupportedProviderError):
            normalize_provider("")


class TestProviderFactory:
    """Validates get_search_provider returns the exact expected class."""

    def test_factory_yandex(self):
        provider = get_search_provider("yandex")
        assert isinstance(provider, YandexVisualProvider)
        assert provider.name == "yandex"

    def test_factory_yandex_alias(self):
        provider = get_search_provider("Yandex_Visual")
        assert isinstance(provider, YandexVisualProvider)

    def test_factory_bing(self):
        provider = get_search_provider("bing")
        assert isinstance(provider, BingVisualProvider)
        assert provider.name == "bing"

    def test_factory_google(self):
        provider = get_search_provider("google")
        assert isinstance(provider, GoogleLensProvider)
        assert provider.name == "google"

    def test_factory_auto(self):
        provider = get_search_provider("auto")
        assert isinstance(provider, AutoVisualProvider)
        assert provider.name == "auto"

    def test_factory_invalid(self):
        with pytest.raises(UnsupportedProviderError):
            get_search_provider("unknown_provider")


class TestSearchResponseContract:
    """Validates the SearchResponse schema and status enum contracts."""

    def test_search_response_success(self):
        candidate = SearchCandidate(
            url="https://example.com/photo.jpg",
            title="Example Photo",
            source_domain="example.com",
            search_rank=1,
            image_url="https://example.com/photo.jpg",
        )
        resp = SearchResponse(
            provider="yandex",
            status=SearchStatus.SUCCESS,
            elapsed_seconds=1.5,
            raw_results_count=10,
            parsed_candidates_count=1,
            candidates=[candidate],
            diagnostics={"browser": "chromium"},
        )
        assert resp.status == SearchStatus.SUCCESS
        assert len(resp.candidates) == 1
        assert resp.candidates[0].source_domain == "example.com"
        assert resp.error is None

    def test_search_response_provider_blocked(self):
        resp = SearchResponse(
            provider="yandex",
            status=SearchStatus.PROVIDER_BLOCKED,
            elapsed_seconds=2.1,
            raw_results_count=0,
            parsed_candidates_count=0,
            candidates=[],
            error="Yandex presented a bot verification/CAPTCHA challenge.",
        )
        assert resp.status == SearchStatus.PROVIDER_BLOCKED
        assert resp.candidates == []
        assert "CAPTCHA" in resp.error

    def test_search_response_no_results(self):
        resp = SearchResponse(
            provider="yandex",
            status=SearchStatus.NO_RESULTS,
            elapsed_seconds=3.0,
            raw_results_count=0,
            parsed_candidates_count=0,
            candidates=[],
            error="Yandex search completed, but no usable candidates were discovered.",
        )
        assert resp.status == SearchStatus.NO_RESULTS
        assert len(resp.candidates) == 0

    def test_search_provider_backward_compatibility(self):
        """Ensures provider.search() returns candidates list matching search_detailed().candidates."""
        provider = YandexVisualProvider()
        # Non-existent image returns UNAVAILABLE without throwing unhandled exceptions
        resp = provider.search_detailed("non_existent_file_xyz.jpg")
        assert resp.status == SearchStatus.UNAVAILABLE
        assert resp.candidates == []
        
        # Test backward-compatible .search() method
        candidates = provider.search("non_existent_file_xyz.jpg")
        assert candidates == []
