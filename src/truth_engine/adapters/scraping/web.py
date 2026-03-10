from __future__ import annotations

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

    def fetch_page(self, url: str) -> dict[str, Any]:
        start = time.monotonic()
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = httpx.get(url, timeout=20.0, follow_redirects=True)
                response.raise_for_status()
                text = response.text[: self._char_limit]
                latency_ms = int((time.monotonic() - start) * 1000)
                debug_adapter(
                    "web",
                    "fetch_page",
                    url=url,
                    status_code=response.status_code,
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
                    "tool": "fetch_page",
                    "reason": f"Fetch failed after {_MAX_RETRIES + 1} attempts: {exc}",
                }
        return {"status": "error", "tool": "fetch_page", "reason": "Unexpected retry exhaustion."}

    def extract_content(self, url: str) -> dict[str, Any]:
        start = time.monotonic()
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = httpx.get(url, timeout=20.0, follow_redirects=True)
                response.raise_for_status()
                extracted = trafilatura.extract(response.text) or ""
                text = extracted[: self._char_limit]
                latency_ms = int((time.monotonic() - start) * 1000)
                debug_adapter(
                    "web",
                    "extract_content",
                    url=url,
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
                    "tool": "extract_content",
                    "reason": f"Extraction failed after {_MAX_RETRIES + 1} attempts: {exc}",
                }
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
                    "tool": "extract_content",
                    "reason": f"Content extraction failed: {exc}",
                }
        return {
            "status": "error",
            "tool": "extract_content",
            "reason": "Unexpected retry exhaustion.",
        }
