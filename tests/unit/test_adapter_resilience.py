"""Tests for adapter resilience — structured error returns instead of crashes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from pydantic import SecretStr

from truth_engine.adapters.scraping.web import WebFetchClient
from truth_engine.adapters.search.serper import SerperSearchClient
from truth_engine.config.settings import Settings


def _settings_with_serper_key() -> Settings:
    return Settings(serper_api_key=SecretStr("test-key"))


def test_serper_timeout_returns_structured_error() -> None:
    """A timeout should return a structured error, not raise."""
    settings = _settings_with_serper_key()
    client = SerperSearchClient(settings)

    with patch("truth_engine.adapters.search.serper.httpx.post") as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Connection timed out")
        result = client.search("warehouse ops", limit=3)

    assert result["status"] == "error"
    assert result["tool"] == "search_web"
    assert "timed out" in result["reason"].lower() or "timeout" in result["reason"].lower()


def test_serper_http_429_returns_structured_error() -> None:
    """An HTTP 429 should return a structured error, not raise."""
    settings = _settings_with_serper_key()
    client = SerperSearchClient(settings)

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Rate limited", request=MagicMock(), response=mock_response
    )

    with patch("truth_engine.adapters.search.serper.httpx.post", return_value=mock_response):
        result = client.search("warehouse ops", limit=3)

    assert result["status"] == "error"
    assert result["tool"] == "search_web"
    reason = result["reason"].lower()
    assert "rate" in reason or "429" in reason or "failed" in reason


def test_serper_success_returns_ok() -> None:
    """A successful response should return results."""
    settings = _settings_with_serper_key()
    client = SerperSearchClient(settings)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "organic": [
            {"title": "Test Result", "link": "https://example.com", "snippet": "A test result."}
        ]
    }

    with patch("truth_engine.adapters.search.serper.httpx.post", return_value=mock_response):
        result = client.search("warehouse ops", limit=3)

    assert result["status"] == "ok"
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Test Result"


def test_web_fetch_client_prefers_scrapling_when_available() -> None:
    settings = Settings(page_content_char_limit=1000)
    client = WebFetchClient(settings)

    fake_fetcher_cls = MagicMock()
    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.text = "<html><body>Scrapling content</body></html>"
    fake_fetcher_cls.fetch.return_value = fake_response

    with patch(
        "truth_engine.adapters.scraping.web._load_scrapling_fetcher",
        return_value=fake_fetcher_cls,
    ), patch("truth_engine.adapters.scraping.web.httpx.get") as mock_get:
        result = client.read_page("https://example.com", include_raw_html=True)

    assert result["status"] == "ok"
    assert result["raw_html"] == "<html><body>Scrapling content</body></html>"
    fake_fetcher_cls.fetch.assert_called_once_with("https://example.com")
    mock_get.assert_not_called()


def test_web_fetch_client_read_page_returns_extracted_content_from_single_fetch() -> None:
    settings = Settings(page_content_char_limit=1000)
    client = WebFetchClient(settings)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.text = "<html><body><main>Useful text</main></body></html>"

    with patch(
        "truth_engine.adapters.scraping.web._load_scrapling_fetcher",
        return_value=None,
    ), patch(
        "truth_engine.adapters.scraping.web.httpx.get",
        return_value=mock_response,
    ) as mock_get, patch(
        "truth_engine.adapters.scraping.web.trafilatura.extract",
        return_value="Useful text",
    ):
        result = client.read_page("https://example.com")

    assert result["status"] == "ok"
    assert result["content"] == "Useful text"
    assert result["extraction_status"] == "ok"
    assert "raw_html" not in result
    mock_get.assert_called_once()
