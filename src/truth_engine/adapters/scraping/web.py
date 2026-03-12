from __future__ import annotations

import importlib
import time
from typing import Any

import httpx
import trafilatura

from truth_engine.config.settings import Settings
from truth_engine.services.logging import debug_adapter

_MAX_RETRIES = 2
_BACKOFF_BASE_S = 1.0


class WebFetchClient:
    def __init__(self, settings: Settings):
        self._char_limit = settings.page_content_char_limit
        self._cache: dict[str, str] = {}

    def read_page(self, url: str, *, include_raw_html: bool = False) -> dict[str, Any]:
        fetched = self._fetch(url)
        if fetched["status"] != "ok":
            return fetched

        extracted = self._extract(fetched["content"], url=url)
        result = {
            "status": "ok",
            "url": url,
            "content": extracted["content"],
            "extraction_status": extracted["status"],
            "extraction_reason": extracted.get("reason"),
        }
        if include_raw_html:
            result["raw_html"] = fetched["content"]
        return result

    def _extract(self, raw_content: str, *, url: str) -> dict[str, Any]:
        start = time.monotonic()
        try:
            extracted = trafilatura.extract(raw_content) or ""
            text = extracted[: self._char_limit]
            latency_ms = int((time.monotonic() - start) * 1000)
            debug_adapter(
                "web",
                "extract_content",
                url=url,
                content_length=len(text),
                latency_ms=latency_ms,
            )
            return {"status": "ok", "content": text}
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            debug_adapter(
                "web",
                "extract_error",
                url=url,
                latency_ms=latency_ms,
                error=str(exc),
            )
            return {
                "status": "error",
                "content": "",
                "reason": f"Content extraction failed: {exc}",
            }

    def _fetch(self, url: str) -> dict[str, Any]:
        cached = self._cache.get(url)
        if cached is not None:
            return {"status": "ok", "url": url, "content": cached}

        start = time.monotonic()
        scrapling_fetcher = _load_scrapling_fetcher()
        request = httpx.Request("GET", url)
        for attempt in range(_MAX_RETRIES + 1):
            try:
                if scrapling_fetcher is not None:
                    response = _scrapling_fetch(scrapling_fetcher, url)
                    status_code = int(getattr(response, "status", 200))
                    if status_code >= 400:
                        raise httpx.HTTPStatusError(
                            f"HTTP {status_code}",
                            request=request,
                            response=httpx.Response(status_code, request=request),
                        )
                    text = _scrapling_response_content(response)[: self._char_limit]
                    backend = "scrapling"
                else:
                    response = httpx.get(url, timeout=20.0, follow_redirects=True)
                    response.raise_for_status()
                    text = response.text[: self._char_limit]
                    status_code = response.status_code
                    backend = "httpx"

                self._cache[url] = text
                latency_ms = int((time.monotonic() - start) * 1000)
                debug_adapter(
                    "web",
                    "fetch_page",
                    url=url,
                    status_code=status_code,
                    backend=backend,
                    content_length=len(text),
                    latency_ms=latency_ms,
                )
                return {"status": "ok", "url": url, "content": text}
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError) as exc:
                latency_ms = int((time.monotonic() - start) * 1000)
                if attempt < _MAX_RETRIES:
                    backoff = _BACKOFF_BASE_S * (2**attempt)
                    debug_adapter(
                        "web",
                        "retry",
                        url=url,
                        attempt=attempt + 1,
                        backoff_s=backoff,
                        error=str(exc),
                    )
                    time.sleep(backoff)
                    continue
                debug_adapter(
                    "web",
                    "error",
                    url=url,
                    latency_ms=latency_ms,
                    error=str(exc),
                )
                return {
                    "status": "error",
                    "tool": "read_page",
                    "reason": f"Fetch failed after {_MAX_RETRIES + 1} attempts: {exc}",
                }
        return {"status": "error", "tool": "read_page", "reason": "Unexpected retry exhaustion."}


def _load_scrapling_fetcher() -> Any | None:
    try:
        fetchers = importlib.import_module("scrapling.fetchers")
    except ImportError:
        return None
    fetcher_cls = getattr(fetchers, "StealthyFetcher", None) or getattr(fetchers, "Fetcher", None)
    if fetcher_cls is None:
        return None
    try:
        return fetcher_cls()
    except Exception:
        return fetcher_cls


def _scrapling_fetch(fetcher: Any, url: str) -> Any:
    if hasattr(fetcher, "fetch"):
        return fetcher.fetch(url)
    if hasattr(fetcher, "get"):
        return fetcher.get(url)
    raise AttributeError("Scrapling fetcher does not expose fetch() or get().")


def _scrapling_response_content(response: Any) -> str:
    for attribute in ("text", "html_content", "html", "body"):
        value = getattr(response, attribute, None)
        if value is None:
            continue
        return value() if callable(value) else str(value)
    return str(response)
