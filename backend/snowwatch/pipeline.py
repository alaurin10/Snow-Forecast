"""One run: fetch every active location, build its snapshot, store it.

A location that fails keeps its last good snapshot; one failing location
never stops the others. Only the blend and multi-model responses are
required; everything else (upper air, ensembles, alerts, SNOTEL) is optional
and a failure there becomes a warning.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from snowwatch import ensembles as ens
from snowwatch.analysis.build import build_snapshot
from snowwatch.analysis.flags import flag_key
from snowwatch.capture import load_fixture
from snowwatch.config import ForecastConfig
from snowwatch.http import Fetcher, FetchError
from snowwatch.inputs import inputs_from_responses
from snowwatch.locations import service
from snowwatch.models import Location
from snowwatch.modelwatch import runs_for
from snowwatch.sources import bc_asws, nws, snotel
from snowwatch.sources.base import Request, fetch
from snowwatch.sources.openmeteo import (
    blend_request,
    clouds_request,
    ensemble_request,
    multimodel_request,
    station_request,
    upper_air_request,
)
from snowwatch.store import repo

log = logging.getLogger("snowwatch.pipeline")

# The pause between locations while their forecasts fall back to the public API (the
# self-hosted server is down): the public API's per-minute limit needs it.
FALLBACK_SPACING_S = 20.0
# Locations fetched at once when nothing spaces them (a self-hosted server): the server
# answers several requests at once, and building stays on one thread.
RUN_WORKERS = 4


@dataclass
class LocationResult:
    location_id: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    doc_bytes: int = 0


def _try(
    fetcher: Fetcher,
    req: Request,
    key: str | None,
    errors: list[str],
    *,
    label: str | None = None,
    allow_fallback: bool = True,
) -> Any | None:
    """An optional request: its failure becomes a warning."""
    try:
        return fetch(fetcher, req, cache_key=key, optional=True, allow_fallback=allow_fallback)
    except FetchError as e:
        errors.append(f"{label or req.name}: {e}")
        return None


def fetch_forecasts(
    fetcher: Fetcher,
    loc: Location,
    cfg: ForecastConfig,
    errors: list[str],
    *,
    cache_prefix: str | None = None,
    allow_fallback: bool = True,
) -> dict[str, Any]:
    """The Open-Meteo forecasts for one place: the blend and the multi-model forecast
    (required: their failure raises FetchError), upper air and clouds (optional: a
    failure is added to `errors`). Saved locations and spots (snowwatch/spots.py) both
    use it; spots never fall back to the public API (`allow_fallback`)."""

    def key(name: str) -> str | None:
        return f"{cache_prefix}/{name}" if cache_prefix else None

    # The richer variable lists (milestone 3) only from a self-hosted server: free there,
    # and the public API keeps today's lean lists. A fallback asks the public API for the
    # same request, which costs more weight but keeps the run whole.
    rich = bool(fetcher.local_url)
    out: dict[str, Any] = {}
    out["blend"] = fetch(
        fetcher,
        blend_request(loc, rich=rich),
        cache_key=key("blend"),
        allow_fallback=allow_fallback,
    )
    out["multi"] = fetch(
        fetcher,
        multimodel_request(loc, cfg.models_for(loc.country), rich=rich),
        cache_key=key("multi"),
        allow_fallback=allow_fallback,
    )
    req = upper_air_request(loc, cfg.upper_air_models(loc.country), rich=rich)
    upper = _try(fetcher, req, key("upper"), errors, allow_fallback=allow_fallback)
    if upper is not None:
        out["upper"] = upper
    cloud_model = cfg.cloud_model(loc.country)
    if cloud_model:
        req = clouds_request(loc, cloud_model)
        clouds = _try(fetcher, req, key("clouds"), errors, allow_fallback=allow_fallback)
        if clouds is not None:
            out["clouds"] = clouds
    return out


class RunMemo:
    """Responses kept between runs (the worker holds one): sources refreshed less often
    than forecasts. SNOTEL's daily values change once a day, so with hourly runs they're
    fetched every `snotel_daily_s` (6 h); its hourly values, NWS alerts and the BC CSV
    are fetched every run."""

    def __init__(
        self, *, snotel_daily_s: float = 6 * 3600, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.snotel_daily_s = snotel_daily_s
        self.clock = clock
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, max_age_s: float) -> Any | None:
        with self._lock:
            hit = self._items.get(key)
        if hit is None or self.clock() - hit[0] > max_age_s:
            return None
        return hit[1]

    def put(self, key: str, data: Any) -> None:
        with self._lock:
            self._items[key] = (self.clock(), data)


@dataclass
class _Known:
    """What one location's fetch needs from the database, read on the calling thread."""

    cached: dict[str, Any]  # ensembles by system, no older than ensemble_max_age_h
    station: dict[str, Any] | None  # its snow station's metadata, if known


@dataclass
class _Fetched:
    """One location's responses, plus the database writes they call for (done on the
    calling thread, since fetches run in a pool)."""

    responses: dict[str, Any]
    errors: list[str]
    ensembles: list[tuple[str, Any]] = field(default_factory=list)  # for ensemble_cache
    stations: list[Any] | None = None  # a state's station list, for snotel_stations
    shadow: list[repo.ShadowRow] = field(default_factory=list)


def _known(conn: sqlite3.Connection, loc: Location, cfg: ForecastConfig, now: datetime) -> _Known:
    cached = repo.cached_ensembles(conn, loc.id, now=now, max_age_h=cfg.ensemble_max_age_h)
    station = repo.station_meta(conn, loc.snotel) if loc.snotel else None
    return _Known(cached, station)


def _station_in(stations: Any, triplet: str) -> dict[str, Any] | None:
    """A station's metadata from a fetched station list, shaped like repo.station_meta."""
    for s in stations or []:
        if s.get("stationTriplet") == triplet and s.get("latitude") is not None:
            return {
                "stationTriplet": triplet,
                "name": s.get("name") or triplet,
                "elevation": s.get("elevation"),
                "latitude": s.get("latitude"),
                "longitude": s.get("longitude"),
            }
    return None


def _fetch_location(
    loc: Location,
    fetcher: Fetcher,
    cfg: ForecastConfig,
    known: _Known,
    *,
    now: datetime,
    ensembles: bool | None,
    bc: Mapping[str, Mapping[str, bc_asws.Series]] | None = None,
    shadow: bool = False,
    memo: RunMemo | None = None,
) -> _Fetched:
    """Every response one location needs. Touches no database, so it can run in a
    thread; see fetch_responses."""
    errors: list[str] = []

    def key(name: str) -> str:
        return f"{loc.id}/{name}"

    # Required: blend and multi-model raise.
    got = _Fetched(fetch_forecasts(fetcher, loc, cfg, errors, cache_prefix=loc.id), errors)
    out = got.responses

    cached = known.cached
    for system in cfg.ensembles:
        req = ensemble_request(loc, system)
        public_due = ensembles is True or system not in cached
        data = None
        if not public_due and fetcher.local_ensemble(system):
            try:  # free; on a failure the cache below covers it, at no public cost
                data = fetch(
                    fetcher, req, cache_key=key(req.name), optional=True, allow_fallback=False
                )
            except FetchError:
                data = None  # why is in fetcher.ensembles_public, logged once per run
        elif public_due:
            data = _try(fetcher, req, key(req.name), errors)
            if data is not None and shadow and fetcher.ensemble_mode == "shadow":
                got.shadow.append(_shadow(fetcher, loc.id, system, req, data, now))
        if data is not None:
            got.ensembles.append((system, data))
            out[req.name] = data
        elif system in cached:
            out[req.name] = cached[system]

    mid = loc.band("mid")
    if loc.country == "US":
        alerts = _try(fetcher, nws.alerts_request(mid.lat, mid.lon), key("nws_alerts"), errors)
        if alerts is not None:
            out["nws_alerts"] = alerts
    station = known.station
    if loc.snotel and bc_asws.is_bc(loc.snotel):
        if bc:
            data = bc_asws.station_slice(
                bc, bc_asws.station_id(loc.snotel), now - timedelta(days=46)
            )
            fetcher.cache(bc_asws.SOURCE, key("bc_asws"), data)
            out["bc_asws"] = data
        else:
            errors.append("bc_asws: no BC snow-pillow data this run")
    elif loc.snotel:
        today = now.date()
        req = snotel.daily_request(loc.snotel, today - timedelta(days=45), today)
        memo_key = f"snotel_daily/{loc.snotel}/{today.isoformat()}"
        daily = memo.get(memo_key, memo.snotel_daily_s) if memo is not None else None
        if daily is not None:
            fetcher.cache(req.source, key("snotel_daily"), daily)  # for `rebuild`
        else:
            daily = _try(fetcher, req, key("snotel_daily"), errors)
            if daily is not None and memo is not None:
                memo.put(memo_key, daily)
        hourly = _try(
            fetcher,
            snotel.hourly_request(loc.snotel, today - timedelta(days=4), today),
            key("snotel_hourly"),
            errors,
        )
        if daily is not None and hourly is not None:
            out["snotel_daily"], out["snotel_hourly"] = daily, hourly
        if station is None:
            state = loc.snotel.split(":")[1]
            stations = _try(
                fetcher, snotel.stations_request(state), key(f"stations_{state}"), errors
            )
            if stations:
                got.stations = stations
                station = _station_in(stations, loc.snotel)
    if loc.snotel and station:
        lat, lon = station.get("latitude"), station.get("longitude")
        elev_ft = station.get("elevation")
        if lat is not None and lon is not None and elev_ft is not None:
            req = station_request(lat, lon, elev_ft * 0.3048, cfg.models_for(loc.country))
            data = _try(fetcher, req, key("station"), errors)
            if data is not None:
                out["station"] = data
    return got


def _save_fetched(conn: sqlite3.Connection, loc: Location, got: _Fetched, now: datetime) -> None:
    """The database writes a fetch called for."""
    stamp = now.isoformat(timespec="seconds")
    for system, data in got.ensembles:
        repo.put_ensemble(conn, loc.id, system, data, stamp)
    if got.stations:
        repo.save_stations(conn, got.stations)


def fetch_responses(
    conn: sqlite3.Connection,
    loc: Location,
    fetcher: Fetcher,
    cfg: ForecastConfig,
    *,
    now: datetime,
    ensembles: bool | None,
    bc: Mapping[str, Mapping[str, bc_asws.Series]] | None = None,
    shadow: list[repo.ShadowRow] | None = None,
    memo: RunMemo | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Every response one location needs, keyed by request name, plus optional-source errors.

    ensembles: True fetches them from the public API now; False reuses the cache
    (fetching only systems with nothing cached); None fetches whatever is missing or
    stale. A system the self-hosted server can answer (OPEN_METEO_ENSEMBLES=local, its run
    fresh) is fetched every run, for free; if the server fails, the cache covers it, and
    the public API only when the public schedule would have asked anyway. In shadow mode
    each public ensemble fetched is also asked of the server, compared into `shadow`.
    """
    got = _fetch_location(
        loc,
        fetcher,
        cfg,
        _known(conn, loc, cfg, now),
        now=now,
        ensembles=ensembles,
        bc=bc,
        shadow=shadow is not None,
        memo=memo,
    )
    _save_fetched(conn, loc, got, now)
    if shadow is not None:
        shadow.extend(got.shadow)
    return got.responses, got.errors


def _shadow(
    fetcher: Fetcher, loc_id: str, system: str, req: Request, public: Any, now: datetime
) -> repo.ShadowRow:
    """Shadow mode: ask the server the same ensemble question and compare its answer."""
    row = repo.ShadowRow(loc_id, system, now.isoformat(timespec="seconds"))
    run = fetcher.ensemble_run(system) if fetcher.ensemble_run else None
    row.local_run = run.isoformat(timespec="seconds") if run else None
    if system not in fetcher.public_runs:
        fetcher.public_runs[system] = ens.public_run(
            lambda url: fetcher.get_json(url, source="open-meteo-data"), system
        )
    pub = fetcher.public_runs[system]
    row.public_run = pub.isoformat(timespec="seconds") if pub else None
    try:
        local = fetcher.shadow_ensemble(req.url, req.params, source=req.source)
    except FetchError as e:
        row.error = str(e)[:300]
        return row
    c = ens.compare(local, public, now)
    row.members_local, row.members_public = c.members_local, c.members_public
    row.reach_local_h = None if c.reach_local_h is None else round(c.reach_local_h, 1)
    row.reach_public_h = None if c.reach_public_h is None else round(c.reach_public_h, 1)
    row.mean_diff_cm, row.max_diff_cm = c.mean_diff_cm, c.max_diff_cm
    return row


def forecast_reserve(locs: list[Location], cfg: ForecastConfig, now: datetime) -> float:
    """Public weight to keep for the required forecasts (blend and multi-model) of this
    run and the rest of today's (UTC), should they all fall back to the public API."""
    hhmm = now.astimezone(UTC).strftime("%H:%M")
    runs = 1 + sum(t > hhmm for t in cfg.schedule.runs_utc)
    per_run = sum(
        blend_request(loc).weight + multimodel_request(loc, cfg.models_for(loc.country)).weight
        for loc in locs
    )
    return round(runs * per_run, 1)


def _ensemble_sources(conn: sqlite3.Connection, fetcher: Fetcher, cfg: ForecastConfig) -> None:
    """In local mode: record where each system's ensembles came from this run (the
    Status page shows it, and since when), and log the ones on the public API once."""
    if fetcher.ensemble_mode != "local":
        return
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    public = []
    for system in cfg.ensembles:
        why = fetcher.ensembles_public.get(system)
        if why is None and system not in fetcher.ensembles_local:
            continue  # not asked this run
        repo.update_ensemble_state(conn, system, why is None, why, stamp)
        if why is not None:
            public.append(f"{ens.label(system)} ({why})")
    if public:
        log.warning("ensembles not self-hosted this run: %s", "; ".join(public))


def fetch_bc(
    fetcher: Fetcher, triplets: Iterable[str | None]
) -> dict[str, dict[str, bc_asws.Series]] | None:
    """BC snow-pillow CSVs, fetched once per run for every BC station in use."""
    wanted = {bc_asws.station_id(t) for t in triplets if t and bc_asws.is_bc(t)}
    if not wanted:
        return None
    out: dict[str, dict[str, bc_asws.Series]] = {}
    for el in bc_asws.ELEMENTS:
        req = bc_asws.csv_request(el)
        try:
            text = fetcher.get_text(req.url, source=req.source)
            out[el] = bc_asws.parse_wide_csv(text, wanted)
        except Exception as e:  # snow pillows are extra: never stop the run for them
            log.warning("BC snow pillows %s: %s", el, e)
    return out or None


def run_location(
    conn: sqlite3.Connection,
    loc: Location,
    fetcher: Fetcher,
    cfg: ForecastConfig,
    *,
    run_id: int,
    now: datetime,
    ensembles: bool | None,
    responses: dict[str, Any] | None = None,
    bc: Mapping[str, Mapping[str, bc_asws.Series]] | None = None,
    memo: RunMemo | None = None,
    model_runs: Mapping[str, str | None] | None = None,
) -> LocationResult:
    """Fetch (unless responses are given), build and store one location."""
    try:
        if responses is None:
            shadow: list[repo.ShadowRow] = []
            responses, warnings = fetch_responses(
                conn,
                loc,
                fetcher,
                cfg,
                now=now,
                ensembles=ensembles,
                bc=bc,
                shadow=shadow,
                memo=memo,
            )
            if shadow:
                repo.save_shadow(conn, run_id, shadow)
        else:
            warnings = []
    except Exception as e:  # one location (even a database error) must never stop the run
        log.exception("location %s failed", loc.id)
        return LocationResult(loc.id, ok=False, errors=[f"{loc.id}: {type(e).__name__}: {e}"])
    return _build_store(conn, loc, cfg, run_id, now, responses, warnings, model_runs)


def _build_store(
    conn: sqlite3.Connection,
    loc: Location,
    cfg: ForecastConfig,
    run_id: int,
    now: datetime,
    responses: dict[str, Any],
    warnings: list[str],
    model_runs: Mapping[str, str | None] | None,
) -> LocationResult:
    """Build one location's snapshot from its responses and store it."""
    result = LocationResult(loc.id, ok=False)
    try:
        stations = {}
        if loc.snotel and (meta := repo.station_meta(conn, loc.snotel)):
            stations[loc.snotel] = meta
        inputs = inputs_from_responses(loc, responses, cfg, stations=stations, warnings=warnings)
        snap, records = build_snapshot(loc, inputs, cfg, now, run_id=run_id)
        if model_runs:
            snap.model_runs = runs_for(cfg.models_for(loc.country), model_runs)
        first = repo.record_flags(conn, loc.id, run_id, [(f.type, flag_key(f)) for f in snap.flags])
        for f in snap.flags:
            f.first_run = first.get((f.type, flag_key(f)))
        result.doc_bytes = repo.save_snapshot(conn, loc.id, run_id, snap)
        repo.save_daily(conn, loc.id, run_id, now.isoformat(timespec="seconds"), records)
        if snap.snotel is not None:
            repo.save_obs(conn, loc.id, snap.snotel)
        if loc.tz is None:
            service.set_tz(conn, loc.id, snap.location.tz)
    except Exception as e:  # one location (even a database error) must never stop the run
        log.exception("location %s failed", loc.id)
        result.errors.append(f"{loc.id}: {type(e).__name__}: {e}")
        return result
    result.ok = True
    result.errors = [f"{loc.id}: {w}" for w in snap.warnings]
    return result


class _FallbackGate:
    """With fetches in a pool: while forecasts fall back to the public API (the server is
    down), locations start FALLBACK_SPACING_S apart, as in a one-at-a-time run."""

    def __init__(self, fetcher: Fetcher, sleep: Callable[[float], None]) -> None:
        self.fetcher = fetcher
        self.sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = now
            if self.fetcher.forecasts_falling_back and self._last is not None:
                start = max(now, self._last + FALLBACK_SPACING_S)
            self._last = start
        if start > now:
            self.sleep(start - now)


def run_all(
    conn: sqlite3.Connection,
    fetcher: Fetcher,
    cfg: ForecastConfig,
    *,
    kind: str = "full",
    only: Iterable[str] | None = None,
    ensembles: bool | None = None,
    now: datetime | None = None,
    spacing_s: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
    workers: int = RUN_WORKERS,
    memo: RunMemo | None = None,
    between: Callable[[], None] | None = None,
) -> tuple[int, list[LocationResult]]:
    """Run every active location (or just `only`). Returns the run id and per-location results.

    With no spacing between locations (a self-hosted server), `workers` threads fetch
    locations at once; each is built and stored on this thread as its fetch finishes
    (the database stays on one thread). With spacing (the public API), one at a time.
    `between` is called on this thread after each location (the worker serves queued
    Manage jobs there, so they don't wait for the whole run)."""
    locs = service.list_locations(conn)
    if only is not None:
        wanted = set(only)
        locs = [loc for loc in locs if loc.id in wanted]
    run_id = repo.start_run(conn, kind)
    fetcher.public_reserve = forecast_reserve(locs, cfg, now or datetime.now(UTC))
    fetcher.ensembles_local.clear()
    fetcher.ensembles_public.clear()
    fetcher.public_runs.clear()
    inits = {k: r.init_time for k, r in repo.model_runs(conn).items()}
    weight_before = fetcher.total_weight
    fallbacks_before = fetcher.fallbacks
    results: list[LocationResult] = []
    crash: list[str] = []

    def done(loc: Location, res: LocationResult, t0: float) -> None:
        log.info(
            "location %s %s in %.1fs (%d KB)",
            loc.id,
            "ok" if res.ok else "FAILED",
            time.monotonic() - t0,
            res.doc_bytes // 1024,
        )
        results.append(res)
        if between is not None:
            try:
                between()
            except Exception:
                log.exception("between locations")

    try:
        bc = fetch_bc(fetcher, [loc.snotel for loc in locs if bc_asws.is_bc(loc.snotel)])
        if spacing_s > 0 or workers <= 1 or len(locs) <= 1:
            fell_back = fetcher.fallbacks
            for i, loc in enumerate(locs):
                if i:
                    public = fetcher.fallbacks > fell_back
                    sleep(max(spacing_s, FALLBACK_SPACING_S) if public else spacing_s)
                    fell_back = fetcher.fallbacks
                t0 = time.monotonic()
                res = run_location(
                    conn,
                    loc,
                    fetcher,
                    cfg,
                    run_id=run_id,
                    now=now or datetime.now(UTC),
                    ensembles=ensembles,
                    bc=bc,
                    memo=memo,
                    model_runs=inits,
                )
                done(loc, res, t0)
        else:
            _run_pooled(
                conn,
                locs,
                fetcher,
                cfg,
                run_id,
                now,
                ensembles,
                bc,
                memo,
                inits,
                workers,
                sleep,
                done,
            )
    except BaseException as e:  # always close the run, then let the error go on
        crash.append(f"run stopped: {type(e).__name__}: {e}")
        raise
    finally:
        order = {loc.id: i for i, loc in enumerate(locs)}
        results.sort(key=lambda r: order.get(r.location_id, len(order)))
        errors = crash + [e for r in results for e in r.errors]
        n_ok = sum(r.ok for r in results)
        if not crash and n_ok == len(locs):  # includes no locations at all
            status = "ok" if not errors else "partial"
        else:
            status = "partial" if n_ok else "failed"
        repo.finish_run(conn, run_id, status, errors, fetcher.total_weight - weight_before)
        repo.record_usage(conn, fetcher)
        repo.save_source_status(conn, fetcher.sources)
        fetcher.sources.clear()
        _ensemble_sources(conn, fetcher, cfg)
        if fallbacks := fetcher.fallbacks - fallbacks_before:
            log.warning(
                "run %d: %d Open-Meteo requests fell back to the public API", run_id, fallbacks
            )
    return run_id, results


def _run_pooled(
    conn: sqlite3.Connection,
    locs: list[Location],
    fetcher: Fetcher,
    cfg: ForecastConfig,
    run_id: int,
    now: datetime | None,
    ensembles: bool | None,
    bc: Mapping[str, Mapping[str, bc_asws.Series]] | None,
    memo: RunMemo | None,
    inits: Mapping[str, str | None],
    workers: int,
    sleep: Callable[[float], None],
    done: Callable[[Location, LocationResult, float], None],
) -> None:
    """Fetch locations in a pool; build and store each here as it arrives."""
    gate = _FallbackGate(fetcher, sleep)
    known = {loc.id: _known(conn, loc, cfg, now or datetime.now(UTC)) for loc in locs}
    started: dict[str, float] = {}

    def job(loc: Location) -> tuple[_Fetched, datetime]:
        gate.wait()
        started[loc.id] = time.monotonic()
        at = now or datetime.now(UTC)
        got = _fetch_location(
            loc,
            fetcher,
            cfg,
            known[loc.id],
            now=at,
            ensembles=ensembles,
            bc=bc,
            shadow=True,
            memo=memo,
        )
        return got, at

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fetch") as pool:
        futures = {pool.submit(job, loc): loc for loc in locs}
        for fut in as_completed(futures):
            loc = futures[fut]
            try:
                got, at = fut.result()
                _save_fetched(conn, loc, got, at)
                if got.shadow:
                    repo.save_shadow(conn, run_id, got.shadow)
            except Exception as e:  # one location must never stop the run
                if not isinstance(e, FetchError):
                    log.exception("location %s failed", loc.id)
                res = LocationResult(
                    loc.id, ok=False, errors=[f"{loc.id}: {type(e).__name__}: {e}"]
                )
                done(loc, res, started.get(loc.id, time.monotonic()))
                continue
            res = _build_store(conn, loc, cfg, run_id, at, got.responses, got.errors, inits)
            done(loc, res, started.get(loc.id, time.monotonic()))


def latest_cached(raw_dir: Path, loc_id: str) -> dict[str, Any]:
    """The newest raw response per request name for one location (for `rebuild`)."""
    out: dict[str, Any] = {}
    for source in raw_dir.iterdir() if raw_dir.exists() else []:
        folder = source / loc_id
        if not folder.is_dir():
            continue
        for name_dir in folder.iterdir():
            files = sorted(name_dir.glob("*.json.gz"))
            if files:
                out[name_dir.name] = load_fixture(files[-1])
    return out
