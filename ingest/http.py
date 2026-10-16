"""Rate-limited, resumable HTTP client for every ingest stage.

Responses are cached on disk. The cache key is a hash of the method, URL and body, so a
second run sends no requests, and a stopped crawl continues from where it stopped. 404
responses are also cached, because a missing package stays missing. 429 and 5xx responses
and transport errors are retried with exponential backoff.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from fallout.settings import CACHE_DIR, SETTINGS

USER_AGENT = f"fallout-hackathon ({SETTINGS['contact_email']})"


class RetryableStatus(Exception):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


def _retryable(exc: BaseException) -> bool:
    return isinstance(exc, (RetryableStatus, httpx.TransportError))


def encode_pkg(name: str) -> str:
    """URL-encodes a package name for a path segment: `@a/b` -> `%40a%2Fb`."""
    return quote(name, safe="")


class CachedClient:
    def __init__(self, cache_dir: Path = CACHE_DIR, concurrency: int = 16, min_interval: float = 0.0) -> None:
        """`min_interval` is the minimum time in seconds between the starts of network requests.
        Cache hits do not wait."""
        self.cache_dir = cache_dir
        self._sem = asyncio.Semaphore(concurrency)
        self._min_interval = min_interval
        self._next_slot = 0.0
        self._pace = asyncio.Lock()
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
        )
        self.hits = 0
        self.misses = 0

    async def __aenter__(self) -> CachedClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    def _path(self, method: str, url: str, body: Any) -> Path:
        key = json.dumps([method, url, body], sort_keys=True)
        h = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / h[:2] / f"{h}.json"

    async def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any | None:
        """Returns the parsed body, or None for a 404."""
        return await self._fetch("GET", url, None, headers)

    async def post_json(self, url: str, body: Any) -> Any | None:
        return await self._fetch("POST", url, body, None)

    async def _fetch(self, method: str, url: str, body: Any, headers: dict[str, str] | None) -> Any | None:
        path = self._path(method, url, body)
        if path.exists():
            self.hits += 1
            cached = json.loads(path.read_text())
            return cached["body"]
        self.misses += 1
        status, payload = await self._request(method, url, body, headers)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"url": url, "status": status, "body": payload}))
        tmp.replace(path)
        return payload

    @retry(
        retry=retry_if_exception(_retryable),
        wait=wait_exponential_jitter(multiplier=2, max=120),
        stop=stop_after_attempt(10),
        reraise=True,
    )
    async def _request(
        self, method: str, url: str, body: Any, headers: dict[str, str] | None
    ) -> tuple[int, Any | None]:
        async with self._sem:
            if self._min_interval:
                async with self._pace:
                    loop = asyncio.get_running_loop()
                    await asyncio.sleep(max(0.0, self._next_slot - loop.time()))
                    self._next_slot = loop.time() + self._min_interval
            resp = await self._client.request(method, url, json=body, headers=headers)
            if resp.status_code == 429:
                # Keep the semaphore slot during the Retry-After wait, so the whole client slows down.
                retry_after = resp.headers.get("retry-after", "")
                await asyncio.sleep(min(float(retry_after), 300) if retry_after.isdigit() else 5)
        if resp.status_code == 404:
            return 404, None
        if resp.status_code == 429 or resp.status_code >= 500:
            raise RetryableStatus(resp.status_code, url)
        resp.raise_for_status()
        return resp.status_code, resp.json()
