"""One run: fetch every active location, build its snapshot, store it.

A location that fails keeps its last good snapshot; one failing location
never stops the others. Only the blend and multi-model responses are
required; everything else (upper air, ensembles, alerts, SNOTEL) is optional
and a failure there becomes a warning.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from snowwatch.analysis.build import build_snapshot
from snowwatch.capture import load_fixture
from snowwatch.config import ForecastConfig
from snowwatch.http import Fetcher, FetchError
from snowwatch.inputs import inputs_from_responses
from snowwatch.locations import service
from snowwatch.models import Location
from snowwatch.sources import nws, snotel
from snowwatch.sources.base import Request, fetch
from snowwatch.sources.openmeteo import (
    blend_request,
    ensemble_request,
    multimodel_request,
    upper_air_request,
)
from snowwatch.store import repo

log = logging.getLogger("snowwatch.pipeline")


@dataclass
class LocationResult:
    location_id: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    doc_bytes: int = 0


def _try(
    fetcher: Fetcher, req: Request, key: str, errors: list[str], *, label: str | None = None
) -> Any | None:
    try:
        return fetch(fetcher, req, cache_key=key)
    except FetchError as e:
        errors.append(f"{label or req.name}: {e}")
        return None


def fetch_responses(
    conn: sqlite3.Connection,
    loc: Location,
    fetcher: Fetcher,
    cfg: ForecastConfig,
    *,
    now: datetime,
    ensembles: bool | None,
) -> tuple[dict[str, Any], list[str]]:
    """Every response one location needs, keyed by request name, plus optional-source errors.

    ensembles: True fetches them now; False reuses the cache (fetching only
    systems with nothing cached); None fetches whatever is missing or stale.
    """
    out: dict[str, Any] = {}
    errors: list[str] = []

    def key(name: str) -> str:
        return f"{loc.id}/{name}"

    # Required: let these raise.
    out["blend"] = fetch(fetcher, blend_request(loc), cache_key=key("blend"))
    out["multi"] = fetch(
        fetcher, multimodel_request(loc, cfg.models_for(loc.country)), cache_key=key("multi")
    )
    upper = _try(
        fetcher, upper_air_request(loc, cfg.upper_air_models(loc.country)), key("upper"), errors
    )
    if upper is not None:
        out["upper"] = upper

    cached = repo.cached_ensembles(conn, loc.id, now=now, max_age_h=cfg.ensemble_max_age_h)
    for system in cfg.ensembles:
        wanted = ensembles is True or system not in cached
        if wanted:
            data = _try(fetcher, ensemble_request(loc, system), key(f"ens_{system}"), errors)
            if data is not None:
                repo.put_ensemble(conn, loc.id, system, data, now.isoformat(timespec="seconds"))
                out[f"ens_{system}"] = data
                continue
        if system in cached:
            out[f"ens_{system}"] = cached[system]

    mid = loc.band("mid")
    if loc.country == "US":
        alerts = _try(fetcher, nws.alerts_request(mid.lat, mid.lon), key("nws_alerts"), errors)
        if alerts is not None:
            out["nws_alerts"] = alerts
    if loc.snotel:
        today = now.date()
        daily = _try(
            fetcher,
            snotel.daily_request(loc.snotel, today - timedelta(days=45), today),
            key("snotel_daily"),
            errors,
        )
        hourly = _try(
            fetcher,
            snotel.hourly_request(loc.snotel, today - timedelta(days=4), today),
            key("snotel_hourly"),
            errors,
        )
        if daily is not None and hourly is not None:
            out["snotel_daily"], out["snotel_hourly"] = daily, hourly
        if repo.station_meta(conn, loc.snotel) is None:
            state = loc.snotel.split(":")[1]
            stations = _try(
                fetcher, snotel.stations_request(state), key(f"stations_{state}"), errors
            )
            if stations:
                repo.save_stations(conn, stations)
    return out, errors


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
) -> LocationResult:
    """Fetch (unless responses are given), build and store one location."""
    result = LocationResult(loc.id, ok=False)
    try:
        if responses is None:
            responses, warnings = fetch_responses(
                conn, loc, fetcher, cfg, now=now, ensembles=ensembles
            )
        else:
            warnings = []
        stations = {}
        if loc.snotel and (meta := repo.station_meta(conn, loc.snotel)):
            stations[loc.snotel] = meta
        inputs = inputs_from_responses(loc, responses, cfg, stations=stations, warnings=warnings)
        snap, records = build_snapshot(loc, inputs, cfg, now, run_id=run_id)
    except Exception as e:  # one location must never stop the run
        log.exception("location %s failed", loc.id)
        result.errors.append(f"{loc.id}: {type(e).__name__}: {e}")
        return result
    result.doc_bytes = repo.save_snapshot(conn, loc.id, run_id, snap)
    repo.save_daily(conn, loc.id, run_id, now.isoformat(timespec="seconds"), records)
    repo.save_alerts(conn, loc.id, run_id, snap.alerts)
    if snap.snotel is not None:
        repo.save_obs(conn, loc.id, snap.snotel)
    if loc.tz is None:
        service.set_tz(conn, loc.id, snap.location.tz)
    result.ok = True
    result.errors = [f"{loc.id}: {w}" for w in snap.warnings]
    return result


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
) -> tuple[int, list[LocationResult]]:
    """Run every active location (or just `only`). Returns the run id and per-location results."""
    locs = service.list_locations(conn)
    if only is not None:
        wanted = set(only)
        locs = [loc for loc in locs if loc.id in wanted]
    run_id = repo.start_run(conn, kind)
    weight_before = fetcher.total_weight
    results: list[LocationResult] = []
    for i, loc in enumerate(locs):
        if i:
            sleep(spacing_s)
        t0 = time.monotonic()
        res = run_location(
            conn,
            loc,
            fetcher,
            cfg,
            run_id=run_id,
            now=now or datetime.now(UTC),
            ensembles=ensembles,
        )
        log.info(
            "location %s %s in %.1fs (%d KB)",
            loc.id,
            "ok" if res.ok else "FAILED",
            time.monotonic() - t0,
            res.doc_bytes // 1024,
        )
        results.append(res)
    errors = [e for r in results for e in r.errors]
    n_ok = sum(r.ok for r in results)
    if results and n_ok == len(results):
        status = "ok" if not errors else "partial"
    else:
        status = "partial" if n_ok else "failed"
    repo.finish_run(conn, run_id, status, errors, fetcher.total_weight - weight_before)
    return run_id, results


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
