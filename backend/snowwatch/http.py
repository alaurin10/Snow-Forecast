"""HTTP client for upstream data: retries, 429 handling, raw-response cache, usage tracking."""

from __future__ import annotations

import gzip
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

RATE_LIMIT_WAIT_S = 65.0  # Open-Meteo's per-minute window, plus a margin
MAX_RETRY_AFTER_S = 120.0  # never wait longer than this on a server's say-so
MAX_BODY_BYTES = 64_000_000  # the ski-area catalog is ~21 MB; nothing else comes close
CONTACT_HOSTS = ("api.weather.gov",)  # NWS asks callers to identify themselves


def _wants_contact(url: str) -> bool:
    return urlsplit(url).hostname in CONTACT_HOSTS


def _retry_after(resp: httpx.Response) -> float | None:
    """Seconds from a Retry-After header (the number form), capped."""
    value = resp.headers.get("retry-after", "")
    try:
        return min(max(float(value), 1.0), MAX_RETRY_AFTER_S)
    except ValueError:
        return None


def strip_queries(text: str) -> str:
    """Drop the query strings from any URLs in an error message (they can be long, and
    the message is shown publicly)."""
    return re.sub(r"(https?://[^\s?)]+)\?[^\s)]*", r"\1", text)


class FetchError(RuntimeError):
    """An upstream request failed after all retries, or was rejected outright."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status  # the HTTP status of an outright rejection (4xx), if any


@dataclass
class SourceStat:
    """What happened with one upstream source during this fetcher's life (for Status)."""

    ok: int = 0
    errors: int = 0
    weight: float = 0.0
    last_error: str | None = None
    last_ok_at: str | None = None
    last_error_at: str | None = None


@dataclass(frozen=True)
class CallRecord:
    source: str
    url: str
    status: int
    weight: float
    elapsed_s: float
    tries: int


class Fetcher:
    """GET JSON with retries.

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
        contact_user_agent: str | None = None,
        time_budget_s: float | None = None,
    ) -> None:
        self._deadline = time.monotonic() + time_budget_s if time_budget_s else None
        # Hosts that ask for contact details get them; every other host gets `user_agent`.
        self._contact_headers = {"User-Agent": contact_user_agent} if contact_user_agent else {}
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
        self.calls: list[CallRecord] = []
        self.rate_limited = 0  # 429 responses seen (each costs a 65 s wait)
        self.sources: dict[str, SourceStat] = {}

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
        resp = self._get(url, params, source=source, weight=weight)
        try:
            data = resp.json()
        except ValueError as e:
            raise self._fail(source, f"response is not JSON ({url})") from e
        if isinstance(data, dict) and data.get("error") is True:
            raise self._fail(source, f"{data.get('reason', 'error')} ({url})")
        self._ok(source, weight)
        if self.raw_dir is not None and cache_key:
            self.cache(source, cache_key, data)
        return data

    def get_text(self, url: str, params: dict[str, str] | None = None, *, source: str) -> str:
        """GET a text body (CSV) with the same retries. Callers cache what they keep."""
        resp = self._get(url, params, source=source, weight=0.0)
        if "text/html" in resp.headers.get("content-type", ""):
            raise self._fail(source, f"got a web page instead of data ({url})")
        self._ok(source, 0.0)
        return resp.text

    def _get(
        self, url: str, params: dict[str, str] | None, *, source: str, weight: float
    ) -> httpx.Response:
        last: str = ""
        started = time.monotonic()
        for i in range(self.tries):
            final = i == self.tries - 1 or self._out_of_time()
            wait = 0.0
            try:
                headers = self._contact_headers if _wants_contact(url) else None
                resp = self._client.get(url, params=params, headers=headers)
            except httpx.TransportError as e:
                last = f"{type(e).__name__}: {e}"
                wait = 2 + 3 * i
            else:
                if resp.status_code == 429:
                    last = "HTTP 429 (rate limited)"
                    self.rate_limited += 1
                    wait = _retry_after(resp) or RATE_LIMIT_WAIT_S
                elif resp.status_code >= 500:
                    last = f"HTTP {resp.status_code}"
                    wait = _retry_after(resp) or 2 + 3 * i
                elif resp.status_code >= 400:
                    raise self._fail(
                        source, f"HTTP {resp.status_code} {_reason(resp)} ({url})", resp.status_code
                    )
                else:
                    if len(resp.content) > MAX_BODY_BYTES:
                        raise self._fail(source, f"response too large ({url})")
                    record = CallRecord(
                        source,
                        str(resp.url),
                        resp.status_code,
                        weight,
                        time.monotonic() - started,
                        i + 1,
                    )
                    self.calls.append(record)
                    return resp
            if final:
                break
            self._sleep(wait)
        tries = i + 1
        raise self._fail(source, f"failed after {tries} tries: {last} ({url})")

    def _out_of_time(self) -> bool:
        """Past the time budget, each request gets one try: an upstream outage must not
        hold the worker for hours."""
        return self._deadline is not None and time.monotonic() > self._deadline

    def _stat(self, source: str) -> SourceStat:
        return self.sources.setdefault(source, SourceStat())

    def _ok(self, source: str, weight: float) -> None:
        st = self._stat(source)
        st.ok += 1
        st.weight += weight
        st.last_ok_at = datetime.now(UTC).isoformat(timespec="seconds")

    def _fail(self, source: str, message: str, status: int | None = None) -> FetchError:
        message = strip_queries(message)  # shown on the public Status page
        st = self._stat(source)
        st.errors += 1
        st.last_error = message[:300]
        st.last_error_at = datetime.now(UTC).isoformat(timespec="seconds")
        return FetchError(f"{source}: {message}", status)

    def cache(self, source: str, key: str, data: Any) -> None:
        """Keep a raw response for 24 h (for `snowwatch rebuild`)."""
        if self.raw_dir is None:
            return
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
    for d in sorted((d for d in raw_dir.rglob("*") if d.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    return removed


def _reason(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        return str(body.get("reason") or body.get("detail") or body.get("title") or "")[:200]
    return ""
