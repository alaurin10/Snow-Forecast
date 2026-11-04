"""HTTP client for upstream data: retries, 429 handling, raw-response cache, usage tracking."""

from __future__ import annotations

import gzip
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

RATE_LIMIT_WAIT_S = 65.0  # Open-Meteo's per-minute window, plus a margin


class FetchError(RuntimeError):
    """An upstream request failed after all retries, or was rejected outright."""


@dataclass(frozen=True)
class CallRecord:
    source: str
    url: str
    status: int
    weight: float
    elapsed_s: float
    tries: int


class Fetcher:
    """GET JSON with retries. Ported from `get()` in docs/reference/pull.py.

    - 429: wait 65 s and retry.
    - 5xx, timeouts and connection errors: back off 2 + 3*i seconds and retry.
    - Other 4xx: fail at once (retrying a bad request never helps).
    """

    def __init__(
        self,
        *,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        raw_dir: Path | None = None,
        tries: int = 6,
        timeout_s: float = 40.0,
        on_call: Callable[[CallRecord], None] | None = None,
    ) -> None:
        self._client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json, application/geo+json",
            },
            timeout=timeout_s,
            transport=transport,
            follow_redirects=True,
        )
        self._sleep = sleep
        self.raw_dir = raw_dir
        self.tries = tries
        self.on_call = on_call
        self.calls: list[CallRecord] = []

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.calls)

    def get_json(
        self,
        url: str,
        params: dict[str, str] | None = None,
        *,
        source: str,
        cache_key: str | None = None,
        weight: float = 0.0,
    ) -> Any:
        last: str = ""
        started = time.monotonic()
        for i in range(self.tries):
            try:
                resp = self._client.get(url, params=params)
            except httpx.TransportError as e:
                last = f"{type(e).__name__}: {e}"
                self._sleep(2 + 3 * i)
                continue
            if resp.status_code == 429:
                last = "HTTP 429 (rate limited)"
                self._sleep(RATE_LIMIT_WAIT_S)
                continue
            if resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                self._sleep(2 + 3 * i)
                continue
            if resp.status_code >= 400:
                raise FetchError(f"{source}: HTTP {resp.status_code} {_reason(resp)} ({url})")
            try:
                data = resp.json()
            except ValueError as e:
                raise FetchError(f"{source}: response is not JSON ({url})") from e
            if isinstance(data, dict) and data.get("error") is True:
                raise FetchError(f"{source}: {data.get('reason', 'error')} ({url})")
            record = CallRecord(
                source, str(resp.url), resp.status_code, weight, time.monotonic() - started, i + 1
            )
            self.calls.append(record)
            if self.on_call:
                self.on_call(record)
            if self.raw_dir is not None and cache_key:
                self._cache(source, cache_key, data)
            return data
        raise FetchError(f"{source}: failed after {self.tries} tries: {last} ({url})")

    def _cache(self, source: str, key: str, data: Any) -> None:
        assert self.raw_dir is not None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        path = self.raw_dir / source / key / f"{stamp}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode()))


def prune_raw(raw_dir: Path, *, max_age_h: float = 24, now: float | None = None) -> int:
    """Delete cached raw responses older than max_age_h. Returns the number removed."""
    if not raw_dir.exists():
        return 0
    cutoff = (now if now is not None else time.time()) - max_age_h * 3600
    removed = 0
    for path in raw_dir.rglob("*.json.gz"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def _reason(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        return str(body.get("reason") or body.get("detail") or body.get("title") or "")[:200]
    return ""
