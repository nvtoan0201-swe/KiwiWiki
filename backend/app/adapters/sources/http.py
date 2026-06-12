"""Shared HTTP plumbing for source adapters: per-adapter rate limiting,
exponential backoff on transient failures, and mapping every terminal failure
to `SourceUnavailable` so one provider going down never kills a search."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.core.errors import SourceUnavailable

logger = logging.getLogger("app.sources")

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RateLimitedHTTP:
    def __init__(
        self,
        name: str,
        *,
        min_interval: float = 0.2,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._name = name
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._timeout = timeout
        self._headers = headers or {}
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout, headers=self._headers)
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _throttle(self) -> None:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        attempt = 0
        last_error: Exception | None = None
        while attempt <= self._max_retries:
            await self._throttle()
            try:
                response = await self._get_client().get(url, params=params)
                if response.status_code in _RETRYABLE_STATUS:
                    raise httpx.HTTPStatusError(
                        f"{response.status_code} from {self._name}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                status = (
                    exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                )
                retryable = status is None or status in _RETRYABLE_STATUS
                last_error = exc
                if retryable and attempt < self._max_retries:
                    delay = self._backoff_base * (2**attempt)
                    logger.warning(
                        "source request retry",
                        extra={
                            "extra": {
                                "adapter": self._name,
                                "attempt": attempt,
                                "status": status,
                            }
                        },
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                raise SourceUnavailable(
                    f"{self._name} unavailable: {exc}", {"adapter": self._name}
                ) from exc
        raise SourceUnavailable(f"{self._name} unavailable: {last_error}", {"adapter": self._name})

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = await self.get(url, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceUnavailable(
                f"{self._name} returned non-JSON", {"adapter": self._name}
            ) from exc

    async def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        response = await self.get(url, params=params)
        return response.text
