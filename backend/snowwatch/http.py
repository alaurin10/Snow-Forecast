"""HTTP client for upstream data: retries, 429 handling, raw-response cache, usage tracking,
and routing Open-Meteo requests to a self-hosted server with a public fallback."""

from __future__ import annotations

import gzip
import json
import logging
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from snowwatch.settings import Settings

log = logging.getLogger("snowwatch.http")

RATE_LIMIT_WAIT_S = 65.0  # Open-Meteo's per-minute window, plus a margin
MAX_RETRY_AFTER_S = 120.0  # never wait longer than this on a server's say-so
MAX_BODY_BYTES = 64_000_000  # the ski-area catalog is ~21 MB; nothing else comes close
CONTACT_HOSTS = ("api.weather.gov",)  # NWS asks callers to identify themselves

# The public Open-Meteo API: forecasts and elevation, which a self-hosted server can
# answer. Ensembles (ensemble-api.open-meteo.com) go to it only with
# OPEN_METEO_ENSEMBLES=local, for systems whose downloaded run is fresh: the public data
# the server reads holds no per-member snowfall (docs/OPEN-METEO-PLAN.md, milestone 1b).
PUBLIC_OPEN_METEO = "https://api.open-meteo.com/v1/"
PUBLIC_ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/"
LOCAL_TIMEOUT_S = 120.0  # an empty cache's first summit request took 52 s
LOCAL_HOST = "local"  # the self-hosted server's row in the usage ledger
LOCAL_SUFFIX = "-local"  # its requests' source name on the Status page: open-meteo-local
# After the server can't be reached, skip it for this long and go straight to the
# fallback, so a stopped container costs one failed connection, not one per request.
LOCAL_RETRY_AFTER_S = 300.0
# Hosts that ask for gentle use get at least this long between requests (the worker
# no longer pauses between locations when forecasts are self-hosted).
HOST_SPACING_S = {
    "api.weather.gov": 0.5,
    "wcc.sc.egov.usda.gov": 0.5,  # NRCS AWDB (SNOTEL)
    "www.env.gov.bc.ca": 0.5,  # BC River Forecast Centre (snow pillows)
}


def _wants_contact(url: str) -> bool:
    return urlsplit(url).hostname in CONTACT_HOSTS


def is_public_open_meteo(host: str | None) -> bool:
    """A host whose calls count against the public Open-Meteo daily limit."""
    return bool(host) and (host == "open-meteo.com" or str(host).endswith(".open-meteo.com"))


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
    weight: float  # what it cost against the public Open-Meteo limit (0 when self-hosted)
    elapsed_s: float
    tries: int
    host: str = ""
    local: bool = False  # answered by the self-hosted Open-Meteo server
    fallback: bool = False  # a public retry after the self-hosted server failed


@dataclass
class HostUsage:
    """Requests to one host in the usage ledger (`store/repo.add_usage`)."""

    weight: float = 0.0
    requests: int = 0
    fallbacks: int = 0
    seconds: float = 0.0


class _LocalFailed(Exception):
    """The self-hosted server failed in a way the public API may not (down, slow, 5xx)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Fetcher:
    """GET JSON with retries.

    - 429: wait 65 s and retry.
    - 5xx, timeouts and connection errors: back off 2 + 3*i seconds and retry.
    - Other 4xx: fail at once (retrying a bad request never helps).

    With `local_url` (a self-hosted Open-Meteo server), every public forecast and
    elevation URL is rewritten to it, in `_route` only; request builders don't change.
    The server gets one try (120 s). On a connection error, timeout or 5xx the request
    is retried once on the public URL when `fallback` is on, the caller allows it, and
    today's public budget has room (`public_used` reads the ledger). With a server
    configured, every public Open-Meteo request checks that budget first.
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
        local_url: str = "",
        fallback: bool = True,
        local_timeout_s: float = LOCAL_TIMEOUT_S,
        local_retry_after_s: float = LOCAL_RETRY_AFTER_S,
        public_used: Callable[[], float] | None = None,
        public_budget: float = 10_000,
        host_spacing: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
        ensemble_mode: str = "public",
        ensemble_stale: Callable[[str], str | None] | None = None,
        ensemble_check: Callable[[str, Any], str | None] | None = None,
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
        self.local_url = local_url.rstrip("/")
        self.fallback = fallback
        self.local_timeout_s = local_timeout_s
        self.local_retry_after_s = local_retry_after_s
        self.public_used = public_used
        self.public_budget = public_budget
        self.host_spacing = HOST_SPACING_S if host_spacing is None else host_spacing
        self._clock = clock
        self._last_at: dict[str, float] = {}  # host -> when its last request started
        self._local_down_until = 0.0
        self._taken = 0  # calls already handed to the ledger (take_usage)
        self.fallbacks = 0  # forecast requests retried on the public API (server failed)
        self.local_errors = 0
        # Ensembles (milestone 1b): OPEN_METEO_ENSEMBLES, why a system can't use the
        # server right now (None = it can), and why an answer from it can't be used.
        self.ensemble_mode = ensemble_mode if self.local_url else "public"
        self.ensemble_stale = ensemble_stale
        self.ensemble_check = ensemble_check
        # The run each system's server copy holds (shadow records), set by fetcher_for.
        self.ensemble_run: Callable[[str], datetime | None] | None = None
        # The public data's run per system, looked up once per run (shadow records).
        self.public_runs: dict[str, datetime | None] = {}
        self.ensembles_local: set[str] = set()  # systems the server answered this fetcher
        self.ensembles_public: dict[str, str] = {}  # system -> why it used the public API
        # Public weight held back for the remaining runs' required forecasts while the
        # server is down (set by the run; applies to optional requests, local/shadow only).
        self.public_reserve = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def total_weight(self) -> float:
        """Weight spent on the public Open-Meteo API (self-hosted requests are free)."""
        return sum(c.weight for c in self.calls if not c.local)

    @property
    def local_requests(self) -> int:
        return sum(c.local for c in self.calls)

    @property
    def local_seconds(self) -> float:
        return sum(c.elapsed_s for c in self.calls if c.local)

    def take_usage(self) -> dict[str, HostUsage]:
        """Open-Meteo requests since the last call, by host (the self-hosted server as
        `LOCAL_HOST`), for the usage ledger. Each request is handed over once."""
        out: dict[str, HostUsage] = {}
        for c in self.calls[self._taken :]:
            if c.local:
                u = out.setdefault(LOCAL_HOST, HostUsage())
            elif is_public_open_meteo(c.host):
                u = out.setdefault(c.host, HostUsage())
            else:
                continue
            u.weight += c.weight
            u.requests += 1
            u.fallbacks += c.fallback
            u.seconds += c.elapsed_s
        self._taken = len(self.calls)
        return out

    def _public_room(self, weight: float, *, optional: bool = False) -> bool:
        """Whether today's public budget can take `weight` more: the ledger plus what this
        fetcher spent and hasn't handed to it yet. An optional request (ensembles, upper
        air, clouds, station) also leaves `public_reserve` for the required forecasts
        while those are falling back (self-hosted ensembles on, milestone 1b)."""
        if self.public_used is None:
            return True
        pending = sum(c.weight for c in self.calls[self._taken :] if not c.local)
        reserve = 0.0
        if optional and self.ensemble_mode != "public" and self.forecasts_falling_back:
            reserve = self.public_reserve
        return self.public_used() + pending + weight + reserve <= self.public_budget

    @property
    def forecasts_falling_back(self) -> bool:
        """Whether forecasts are going to the public API: the server failed this run."""
        return self.fallbacks > 0 or self._clock() < self._local_down_until

    def local_ensemble(self, system: str) -> bool:
        """Whether `system`'s ensembles go to the server: OPEN_METEO_ENSEMBLES=local and
        its downloaded run is fresh. When not, the reason is kept for the run's log."""
        if self.ensemble_mode != "local":
            return False
        why = self.ensemble_stale(system) if self.ensemble_stale else None
        if why:
            self.ensembles_public.setdefault(system, why)
            return False
        return True

    def _route(self, url: str, params: dict[str, str] | None = None) -> str | None:
        """The self-hosted URL for a public forecast or elevation URL, or an ensemble URL
        for a system the server can answer, else None."""
        if not self.local_url:
            return None
        if url.startswith(PUBLIC_OPEN_METEO):
            return f"{self.local_url}/v1/{url[len(PUBLIC_OPEN_METEO) :]}"
        if url.startswith(PUBLIC_ENSEMBLE) and self.local_ensemble(_system(params)):
            return f"{self.local_url}/v1/{url[len(PUBLIC_ENSEMBLE) :]}"
        return None

    def shadow_ensemble(self, url: str, params: dict[str, str] | None, *, source: str) -> Any:
        """Shadow mode: the server's answer to a public ensemble request, whatever its
        freshness, with no fallback (FetchError on any failure)."""
        if not (self.local_url and url.startswith(PUBLIC_ENSEMBLE)):
            raise FetchError(f"{source}: not an ensemble request ({url})")
        local = f"{self.local_url}/v1/{url[len(PUBLIC_ENSEMBLE) :]}"
        local_source = source + LOCAL_SUFFIX
        try:
            resp, _ = self._get_local(local, params, source=local_source)
        except _LocalFailed as e:
            raise self._fail(local_source, f"self-hosted server {e.message} ({local})") from e
        try:
            data = resp.json()
        except ValueError as e:
            raise self._fail(local_source, f"response is not JSON ({local})") from e
        self._ok(local_source, 0.0)
        return data

    def get_json(
        self,
        url: str,
        params: dict[str, str] | None = None,
        *,
        source: str,
        cache_key: str | None = None,
        weight: float = 0.0,
        allow_fallback: bool = True,
        optional: bool = False,
    ) -> Any:
        resp, rec, used = self._fetch(url, params, source, weight, allow_fallback, optional)
        try:
            data = resp.json()
        except ValueError as e:
            raise self._fail(used, f"response is not JSON ({url})") from e
        if isinstance(data, dict) and data.get("error") is True:
            raise self._fail(used, f"{data.get('reason', 'error')} ({url})")
        self._ok(used, rec.weight)
        if self.raw_dir is not None and cache_key:
            self.cache(source, cache_key, data)
        return data

    def get_text(self, url: str, params: dict[str, str] | None = None, *, source: str) -> str:
        """GET a text body (CSV) with the same retries. Callers cache what they keep."""
        resp, _, used = self._fetch(url, params, source, 0.0, True, False)
        if "text/html" in resp.headers.get("content-type", ""):
            raise self._fail(used, f"got a web page instead of data ({url})")
        self._ok(used, 0.0)
        return resp.text

    def _fetch(
        self,
        url: str,
        params: dict[str, str] | None,
        source: str,
        weight: float,
        allow_fallback: bool,
        optional: bool,
    ) -> tuple[httpx.Response, CallRecord, str]:
        """The response, its call record, and the source name its outcome counts under."""
        local = self._route(url, params)
        if local is None:
            public = self.local_url and is_public_open_meteo(urlsplit(url).hostname)
            if public and not self._public_room(weight, optional=optional):
                raise self._fail(source, f"today's public Open-Meteo budget is spent ({url})")
            resp, rec = self._get(url, params, source=source, weight=weight)
            return resp, rec, source
        ensemble = url.startswith(PUBLIC_ENSEMBLE)
        system = _system(params)
        local_source = source + LOCAL_SUFFIX
        if self._clock() < self._local_down_until:
            why = "not answering (skipped for a few minutes)"
        else:
            try:
                resp, rec = self._get_local(local, params, source=local_source)
                problem = self._ensemble_problem(system, resp) if ensemble else None
                if problem is None:
                    if ensemble:
                        self.ensembles_local.add(system)
                    return resp, rec, local_source
                why = f"answered {system} unusably: {problem}"
                self._fail(local_source, f"{why} ({local})")
            except _LocalFailed as e:
                why = e.message
            except FetchError as e:  # refused (4xx): final for forecasts, not ensembles
                if not ensemble:
                    raise
                why = f"refused {system}: {e}"
        if ensemble:
            self.ensembles_public[system] = why
        refusal = None
        # Ensembles fall back on their own (public is their usual source); forecasts only
        # with OPEN_METEO_FALLBACK.
        if not ((ensemble or self.fallback) and allow_fallback):
            refusal = "no public fallback here"
        elif not self._public_room(weight, optional=optional):
            refusal = "no public fallback: today's public budget is spent"
        if refusal:
            raise self._fail(local_source, f"self-hosted server {why}; {refusal} ({local})")
        if ensemble:
            log.info("self-hosted ensembles: %s; using the public API", why)
        else:
            if not self.fallbacks:
                log.warning("self-hosted Open-Meteo %s; using the public API", why)
            self.fallbacks += 1
        resp, rec = self._get(url, params, source=source, weight=weight, fallback=True)
        return resp, rec, source

    def _ensemble_problem(self, system: str, resp: httpx.Response) -> str | None:
        """Why the server's ensemble answer can't be used (ensemble_check), else None."""
        if self.ensemble_check is None:
            return None
        try:
            data = resp.json()
        except ValueError:
            return "not JSON"
        return self.ensemble_check(system, data)

    def _get_local(
        self, url: str, params: dict[str, str] | None, *, source: str
    ) -> tuple[httpx.Response, CallRecord]:
        """One try at the self-hosted server. Raises _LocalFailed when the public API
        might do better, FetchError for a request the server refused (4xx)."""
        started = time.monotonic()
        try:
            resp = self._client.get(url, params=params, timeout=self.local_timeout_s)
        except httpx.TransportError as e:
            self._local_down_until = self._clock() + self.local_retry_after_s
            self.local_errors += 1
            message = f"failed: {type(e).__name__}: {e}"
            self._fail(source, f"{message} ({url})")
            raise _LocalFailed(message) from e
        if resp.status_code >= 500 or resp.status_code == 429:
            self.local_errors += 1
            self._fail(source, f"HTTP {resp.status_code} ({url})", resp.status_code)
            raise _LocalFailed(f"answered HTTP {resp.status_code}")
        if resp.status_code >= 400:
            self.local_errors += 1
            raise self._fail(
                source, f"HTTP {resp.status_code} {_reason(resp)} ({url})", resp.status_code
            )
        if len(resp.content) > MAX_BODY_BYTES:
            raise self._fail(source, f"response too large ({url})")
        rec = CallRecord(
            source,
            str(resp.url),
            resp.status_code,
            0.0,
            time.monotonic() - started,
            1,
            host=LOCAL_HOST,
            local=True,
        )
        self.calls.append(rec)
        return resp, rec

    def _space(self, url: str) -> None:
        """Wait out a polite host's minimum spacing since its last request."""
        host = urlsplit(url).hostname or ""
        gap = self.host_spacing.get(host)
        if not gap:
            return
        last = self._last_at.get(host)
        if last is not None:
            wait = last + gap - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_at[host] = self._clock()

    def _get(
        self,
        url: str,
        params: dict[str, str] | None,
        *,
        source: str,
        weight: float,
        fallback: bool = False,
    ) -> tuple[httpx.Response, CallRecord]:
        last: str = ""
        started = time.monotonic()
        for i in range(self.tries):
            final = i == self.tries - 1 or self._out_of_time()
            wait = 0.0
            try:
                self._space(url)
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
                        weight if is_public_open_meteo(resp.url.host) else 0.0,
                        time.monotonic() - started,
                        i + 1,
                        host=resp.url.host,
                        fallback=fallback,
                    )
                    self.calls.append(record)
                    return resp, record
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


def _system(params: dict[str, str] | None) -> str:
    """An ensemble request's system (its `models`)."""
    return (params or {}).get("models", "")


def fetcher_for(settings: Settings, **kw: Any) -> Fetcher:
    """A Fetcher set up from the settings: OPEN_METEO_URL routes forecasts and elevation
    to the self-hosted server, OPEN_METEO_FALLBACK allows the public retry, the usage
    ledger in the database keeps public calls within OPEN_METEO_DAILY_BUDGET, and
    OPEN_METEO_ENSEMBLES=local sends fresh systems' ensembles to the server too."""
    from snowwatch import ensembles
    from snowwatch.sources.openmeteo import ENSEMBLE_MEMBERS

    def public_used() -> float:
        from snowwatch.store import repo
        from snowwatch.store.db import connect

        if not settings.database.exists():
            return 0.0
        conn = connect(settings.database, readonly=True)
        try:
            return repo.usage_today(conn).public_weight
        except sqlite3.Error:  # not migrated yet: nothing recorded
            return 0.0
        finally:
            conn.close()

    opts: dict[str, Any] = {
        "user_agent": settings.user_agent,
        "contact_user_agent": settings.contact_user_agent,
        "local_url": settings.open_meteo_url,
        "fallback": settings.open_meteo_fallback,
        "public_used": public_used if settings.local_open_meteo else None,
        "public_budget": settings.open_meteo_daily_budget,
        "ensemble_mode": settings.ensemble_mode,
        "ensemble_stale": lambda system: ensembles.stale_reason(
            settings.open_meteo_data_dir, system
        ),
        "ensemble_check": lambda system, data: ensembles.response_problem(
            system, data, ENSEMBLE_MEMBERS.get(system, 10)
        ),
    }
    fetcher = Fetcher(**(opts | kw))
    fetcher.ensemble_run = lambda system: ensembles.local_run(settings.open_meteo_data_dir, system)
    return fetcher


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
