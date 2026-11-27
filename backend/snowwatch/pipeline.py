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
from collections.abc import Callable, Iterable, Mapping
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


@dataclass
class LocationResult:
    location_id: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    doc_bytes: int = 0


def _try(
    fetcher: Fetcher, req: Request, key: str, errors: list[str], *, label: str | None = None
) -> Any | None:
    """An optional request: its failure becomes a warning."""
    try:
        return fetch(fetcher, req, cache_key=key, optional=True)
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
    bc: Mapping[str, Mapping[str, bc_asws.Series]] | None = None,
    shadow: list[repo.ShadowRow] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Every response one location needs, keyed by request name, plus optional-source errors.

    ensembles: True fetches them from the public API now; False reuses the cache
    (fetching only systems with nothing cached); None fetches whatever is missing or
    stale. A system the self-hosted server can answer (OPEN_METEO_ENSEMBLES=local, its run
    fresh) is fetched every run, for free; if the server fails, the cache covers it, and
    the public API only when the public schedule would have asked anyway. In shadow mode
    each public ensemble fetched is also asked of the server, compared into `shadow`.
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
    cloud_model = cfg.cloud_model(loc.country)
    if cloud_model:
        clouds = _try(fetcher, clouds_request(loc, cloud_model), key("clouds"), errors)
        if clouds is not None:
            out["clouds"] = clouds

    cached = repo.cached_ensembles(conn, loc.id, now=now, max_age_h=cfg.ensemble_max_age_h)
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
            if data is not None and shadow is not None and fetcher.ensemble_mode == "shadow":
                shadow.append(_shadow(fetcher, loc.id, system, req, data, now))
        if data is not None:
            repo.put_ensemble(conn, loc.id, system, data, now.isoformat(timespec="seconds"))
            out[req.name] = data
        elif system in cached:
            out[req.name] = cached[system]

    mid = loc.band("mid")
    if loc.country == "US":
        alerts = _try(fetcher, nws.alerts_request(mid.lat, mid.lon), key("nws_alerts"), errors)
        if alerts is not None:
            out["nws_alerts"] = alerts
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
    if loc.snotel and (meta := repo.station_meta(conn, loc.snotel)):
        lat, lon, elev_ft = meta.get("latitude"), meta.get("longitude"), meta.get("elevation")
        if lat is not None and lon is not None and elev_ft is not None:
            req = station_request(lat, lon, elev_ft * 0.3048, cfg.models_for(loc.country))
            data = _try(fetcher, req, key("station"), errors)
            if data is not None:
                out["station"] = data
    return out, errors


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
) -> LocationResult:
    """Fetch (unless responses are given), build and store one location."""
    result = LocationResult(loc.id, ok=False)
    try:
        if responses is None:
            shadow: list[repo.ShadowRow] = []
            responses, warnings = fetch_responses(
                conn, loc, fetcher, cfg, now=now, ensembles=ensembles, bc=bc, shadow=shadow
            )
            if shadow:
                repo.save_shadow(conn, run_id, shadow)
        else:
            warnings = []
        stations = {}
        if loc.snotel and (meta := repo.station_meta(conn, loc.snotel)):
            stations[loc.snotel] = meta
        inputs = inputs_from_responses(loc, responses, cfg, stations=stations, warnings=warnings)
        snap, records = build_snapshot(loc, inputs, cfg, now, run_id=run_id)
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
    fetcher.public_reserve = forecast_reserve(locs, cfg, now or datetime.now(UTC))
    fetcher.ensembles_local.clear()
    fetcher.ensembles_public.clear()
    fetcher.public_runs.clear()
    weight_before = fetcher.total_weight
    fallbacks_before = fetcher.fallbacks
    results: list[LocationResult] = []
    crash: list[str] = []
    try:
        bc = fetch_bc(fetcher, [loc.snotel for loc in locs if bc_asws.is_bc(loc.snotel)])
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
            )
            log.info(
                "location %s %s in %.1fs (%d KB)",
                loc.id,
                "ok" if res.ok else "FAILED",
                time.monotonic() - t0,
                res.doc_bytes // 1024,
            )
            results.append(res)
    except BaseException as e:  # always close the run, then let the error go on
        crash.append(f"run stopped: {type(e).__name__}: {e}")
        raise
    finally:
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
