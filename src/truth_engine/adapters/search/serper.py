from __future__ import annotations

import time
from typing import Any

import httpx

from truth_engine.config.settings import Settings
from truth_engine.services.logging import debug_adapter

_MAX_RETRIES = 2
_BACKOFF_BASE_S = 1.0


class SerperSearchClient:
    def __init__(self, settings: Settings):
        api_key = settings.serper_api_key
        if api_key is None:
            raise ValueError("TRUTH_ENGINE_SERPER_API_KEY is not configured.")
        self._api_key = api_key.get_secret_value()

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        start = time.monotonic()
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = httpx.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": self._api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": limit},
                    timeout=15.0,
                )
                response.raise_for_status()
                data = response.json()
                results = [
                    {
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    }
                    for item in data.get("organic", [])[:limit]
                ]
                latency_ms = int((time.monotonic() - start) * 1000)
                debug_adapter(
                    "serper",
                    "search",
                    query=query,
                    results=len(results),
                    latency_ms=latency_ms,
                    status="ok",
                )
                return {"status": "ok", "query": query, "results": results}
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError) as exc:
                latency_ms = int((time.monotonic() - start) * 1000)
                if attempt < _MAX_RETRIES:
                    backoff = _BACKOFF_BASE_S * (2**attempt)
                    debug_adapter(
                        "serper",
                        "retry",
                        query=query,
                        attempt=attempt + 1,
                        backoff_s=backoff,
                        error=str(exc),
                    )
                    time.sleep(backoff)
                    continue
                debug_adapter(
                    "serper",
                    "error",
                    query=query,
                    latency_ms=latency_ms,
                    error=str(exc),
                )
                return {
                    "status": "error",
                    "tool": "search_web",
                    "reason": f"Search failed after {_MAX_RETRIES + 1} attempts: {exc}",
                }
        return {"status": "error", "tool": "search_web", "reason": "Unexpected retry exhaustion."}
