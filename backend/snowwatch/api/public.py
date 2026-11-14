"""Read-only endpoints for location data."""

from __future__ import annotations

import gzip
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from snowwatch import avalanche, observations, stations
from snowwatch import avalanche_zones as zones
from snowwatch.analysis.flags import SEVERITY, avalanche_flag
from snowwatch.api.models import (
    BandSummary,
    BestDay,
    ConcernOut,
    DangerChip,
    LocationAge,
    LocationSummary,
    MapWindLocation,
    MapWindOut,
    NearbyOut,
    NearbyReport,
    NearbyStation,
    OverviewPeriod,
    OverviewRow,
    PlanDate,
    PlanOut,
    PlanRow,
    RunOut,
    SourceRow,
    StatusOut,
    TrendOut,
    TrendRun,
)
from snowwatch.avalanche import AvalancheView
from snowwatch.avalanche_zones import ZonesOut
from snowwatch.doc import Snapshot
from snowwatch.geo import haversine_km
from snowwatch.locations import service
from snowwatch.settings import Settings
from snowwatch.store import repo
from snowwatch.store.db import connect
from snowwatch.verify import VerificationOut, headline_source, verification

CACHE = "public, max-age=300, stale-while-revalidate=3600"


def db(request: Request) -> Iterator[sqlite3.Connection]:
    settings: Settings = request.app.state.settings
    if not settings.database.exists():
        raise HTTPException(503, "no database yet; run `snowwatch init`")
    conn = connect(settings.database, readonly=True)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(db)]

# The map's avalanche zones as last served: (file times, when, JSON, gzipped JSON).
_zones_cache: dict[str, tuple[tuple[float, float], datetime, bytes, bytes]] = {}
WET_FLAGS = {"rapid_warming", "rain_on_snow"}
CONCERN_CAPTION = (
    "Experimental estimate from the bulletin and terrain shape. Not a forecast. "
    "Doesn't show runouts or slopes above you."
)

# Around a location (the Observed tab): how far to look, and how many to list.
NEARBY_KM = 60.0
NEARBY_STATIONS = 8
NEARBY_REPORTS = 8
# The map's station and report files as last read: path → (file time, parsed).
_stations_cache: dict[str, tuple[float, stations.StationsOut | None]] = {}
_obs_cache: dict[str, tuple[float, observations.ObsOut | None]] = {}

# Decoded snapshots, by location: (run_id, snapshot). A newer run replaces the entry.
_snapshots: dict[str, tuple[int, Snapshot]] = {}


def latest_snapshots(conn: sqlite3.Connection) -> dict[str, Snapshot]:
    """The newest snapshot of every location, decoding only those that changed."""
    latest = {
        r["location_id"]: r["run_id"]
        for r in conn.execute(
            "SELECT location_id, MAX(run_id) AS run_id FROM snapshots GROUP BY location_id"
        )
    }
    out: dict[str, Snapshot] = {}
    for loc_id, run_id in latest.items():
        cached = _snapshots.get(loc_id)
        if cached is None or cached[0] != run_id:
            snap = repo.latest_snapshot(conn, loc_id)
            if snap is None:
                continue
            _snapshots[loc_id] = cached = (run_id, snap)
        out[loc_id] = cached[1]
    return out


def _cached[T](
    cache: dict[str, tuple[float, T | None]], path: Path, read: Callable[[Path], T | None]
) -> T | None:
    """A file parsed once per change (its modification time), or None while it is missing."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = cache.get(str(path))
    if hit is None or hit[0] != mtime:
        hit = (mtime, read(path))
        cache[str(path)] = hit
    return hit[1]


def danger_for(v: AvalancheView | None, day: str | None) -> DangerChip:
    """The highest rating on `day` (or today), if the forecast is current and covers it."""
    if v is None:
        return DangerChip(level=None, status="none")
    if v.status != "current" or v.doc is None:
        return DangerChip(level=None, status=v.status)
    if day is None:
        if v.today_max is None:
            return DangerChip(level=None, status="not_issued")
        return DangerChip(level=v.today_max, status="current")
    levels = [
        lvl
        for d in v.doc.days
        if d.date == day
        for lvl in (d.alpine, d.treeline, d.below)
        if lvl is not None
    ]
    if not levels:
        return DangerChip(level=None, status="not_issued")
    return DangerChip(level=max(levels), status="current")


def best_day(snap: Snapshot) -> BestDay | None:
    """The best-rated day (earliest on a tie), when it's at least Good."""
    rated = [d for d in snap.days if d.score is not None and d.rating is not None]
    if not rated:
        return None
    top = max(d.score or 0 for d in rated)
    if top < 3:
        return None
    d = next(d for d in rated if d.score == top)
    assert d.rating is not None and d.score is not None
    return BestDay(date=d.date, label=d.label, rating=d.rating, score=d.score)


def avalanche_views(conn: sqlite3.Connection) -> dict[str, AvalancheView]:
    locs = service.list_locations(conn)
    return avalanche.views(conn, {loc.id: loc.tz or "UTC" for loc in locs})


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def make_router() -> APIRouter:
    router = APIRouter(prefix="/api")
    _snapshots.clear()  # a new app may point at a different database
    _zones_cache.clear()
    _stations_cache.clear()
    _obs_cache.clear()

    @router.get("/locations", response_model=list[LocationSummary])
    def locations(conn: Conn, response: Response) -> list[LocationSummary]:
        out = []
        snaps = latest_snapshots(conn)
        for loc in service.list_locations(conn):
            item = LocationSummary(
                id=loc.id,
                name=loc.name,
                kind=loc.kind,
                region=loc.region,
                country=loc.country,
                tz=loc.tz,
                bands=[BandSummary(band=b.band, label=b.label, elev_m=b.elev_m) for b in loc.bands],
            )
            snap = snaps.get(loc.id)
            if snap is not None:
                mid = snap.bands[1]
                w5, w10 = mid.windows["next5"], mid.windows["d6_10"]
                item.run_id = snap.run_id
                item.generated_at = snap.generated_at
                item.next5_cm = w5.snow_cm
                item.next5_p10_cm = w5.ens.p10 if w5.ens else None
                item.next5_p90_cm = w5.ens.p90 if w5.ens else None
                item.d6_10_cm = w10.snow_cm
                item.last24_cm = mid.stats.last24_cm
                item.alerts = len(snap.alerts)
            out.append(item)
        response.headers["Cache-Control"] = CACHE
        return out

    @router.get("/overview", response_model=list[OverviewRow])
    def overview(conn: Conn, response: Response) -> list[OverviewRow]:
        """Every active location with its headline numbers and 20 period totals."""
        snaps = latest_snapshots(conn)
        avy = avalanche_views(conn)
        rows = []
        for loc in service.list_locations(conn):
            row = OverviewRow(
                id=loc.id,
                name=loc.name,
                kind=loc.kind,
                region=loc.region,
                country=loc.country,
                danger=danger_for(avy.get(loc.id), None),
            )
            snap = snaps.get(loc.id)
            if snap is not None:
                mid = snap.bands[1]
                w5, w10 = mid.windows["next5"], mid.windows["d6_10"]
                row.run_id = snap.run_id
                row.generated_at = snap.generated_at
                row.last24_cm = mid.stats.last24_cm
                row.next5_cm = w5.snow_cm
                row.next5_p10_cm = w5.ens.p10 if w5.ens else None
                row.next5_p90_cm = w5.ens.p90 if w5.ens else None
                row.d6_10_cm = w10.snow_cm
                row.alerts = [a.event or "Alert" for a in snap.alerts]
                row.snow_depth_cm = snap.snotel.depth_cm if snap.snotel else None
                row.periods = [
                    OverviewPeriod(
                        key=p.key,
                        label=p.label,
                        kind=p.kind,
                        date=p.date,
                        snow_cm=p.snow_cm,
                        ptype=p.ptype,
                        rain_mm=p.rain_mm,
                    )
                    for p in mid.periods
                ]
                row.best_day = best_day(snap)
                row.powder_dates = [d.date for d in snap.days if d.rating == "Powder"]
                flags = list(snap.flags)
                v = avy.get(loc.id)
                extra = avalanche_flag(v.today_max, None) if v and v.status == "current" else None
                if extra is not None:
                    flags.append(extra)
                row.flags = sorted(flags, key=lambda f: SEVERITY.get(f.severity, 3))
            mid_band = loc.band("mid")
            row.lat, row.lon = mid_band.lat, mid_band.lon
            rows.append(row)
        response.headers["Cache-Control"] = CACHE
        return rows

    @router.get("/map/wind", response_model=MapWindOut)
    def map_wind(conn: Conn, request: Request, response: Response) -> MapWindOut:
        """Every location's loading roses: the wind behind the map's wind-effect layer."""
        cfg = request.app.state.forecast_config.backcountry
        snaps = latest_snapshots(conn)
        out = []
        for loc in service.list_locations(conn):
            snap = snaps.get(loc.id)
            if snap is None or snap.backcountry is None:
                continue
            top = loc.band("summit")
            out.append(
                MapWindLocation(
                    id=loc.id,
                    name=loc.name,
                    lat=top.lat,
                    lon=top.lon,
                    generated_at=snap.generated_at,
                    roses=snap.backcountry.rose,
                    flags=[f for f in snap.flags if f.type in WET_FLAGS],
                )
            )
        response.headers["Cache-Control"] = CACHE
        return MapWindOut(
            min_snow_cm=cfg.rose_min_snow_cm, min_wind_kmh=cfg.rose_min_wind_kmh, locations=out
        )

    @router.get("/map/concern", response_model=ConcernOut)
    def map_concern(request: Request, response: Response) -> ConcernOut:
        """The concern index's settings (see MAP-PLAN B7.3); 404 when HAZARD_INDEX is off."""
        settings: Settings = request.app.state.settings
        if settings.hazard_index == "off":
            raise HTTPException(404, "the concern index is off on this server")
        t = request.app.state.forecast_config.terrain
        response.headers["Cache-Control"] = CACHE
        return ConcernOut(
            caption=CONCERN_CAPTION,
            slope=[list(x) for x in t.concern_slope],
            match_listed=t.concern_match_listed,
            match_other=t.concern_match_other,
            match_none=t.concern_match_none,
            wind_loaded=t.concern_wind_loaded,
            wind_scoured=t.concern_wind_scoured,
            wind_effect=t.concern_wind_effect,
            wind_snow_cm=t.concern_wind_snow_cm,
            sun=t.concern_sun,
            sun_hours=t.concern_sun_hours,
            classes=list(t.concern_classes),
        )

    @router.get("/avalanche/zones.geojson", response_model=ZonesOut)
    def avalanche_zones(conn: Conn, request: Request) -> Response:
        """Every forecast zone in the map's box, as published, with expiry applied now,
        and the approximate treeline bands the map's avalanche layers use."""
        settings: Settings = request.app.state.settings
        path = settings.zones_path
        tl_path = settings.config_dir / "treeline.yaml"
        try:
            key = (path.stat().st_mtime, tl_path.stat().st_mtime if tl_path.exists() else 0)
        except OSError as e:
            raise HTTPException(503, "avalanche zones not fetched yet") from e
        now = datetime.now(UTC)
        hit = _zones_cache.get("zones")
        if hit is None or hit[0] != key or (now - hit[1]).total_seconds() > 60:
            treeline = zones.load_treeline(tl_path)
            out = zones.zones_out(
                zones.read_zones(path),
                now,
                treeline,
                zones.treeline_spots(treeline, service.list_locations(conn)),
                request.app.state.forecast_config.terrain.problem_slope_deg,
            )
            body = out.model_dump_json().encode()
            hit = (key, now, body, gzip.compress(body, 6))
            _zones_cache["zones"] = hit
        # Expiry is checked against the clock, so this is only cached for a minute.
        headers = {"Cache-Control": "public, max-age=60", "Vary": "Accept-Encoding"}
        if "gzip" in request.headers.get("accept-encoding", ""):
            headers["Content-Encoding"] = "gzip"
            return Response(hit[3], media_type="application/geo+json", headers=headers)
        return Response(hit[2], media_type="application/geo+json", headers=headers)

    @router.get("/avalanche", response_model=dict[str, AvalancheView])
    def avalanche_all(conn: Conn, response: Response) -> dict[str, AvalancheView]:
        """Every location's avalanche forecast, with expiry applied at request time."""
        response.headers["Cache-Control"] = "public, max-age=60"
        return avalanche_views(conn)

    @router.get("/plan", response_model=PlanOut)
    def plan(
        conn: Conn, response: Response, day: str | None = Query(None, alias="date")
    ) -> PlanOut:
        """Plan a day: every location's facts (and resort ratings) for one date."""
        snaps = latest_snapshots(conn)
        locs = service.list_locations(conn)
        labels: dict[str, str] = {}
        for loc in locs:
            snap = snaps.get(loc.id)
            for d in snap.days if snap else []:
                labels.setdefault(d.date, d.label)
        dates = sorted(labels)[:10]
        if day is None:
            if not dates:
                raise HTTPException(404, "no forecasts yet")
            day = dates[0]
        elif day not in dates:
            raise HTTPException(400, f"no forecast for {day}; choose one of {', '.join(dates)}")
        avy = avalanche_views(conn)
        rows = []
        for loc in locs:
            snap = snaps.get(loc.id)
            found = next((d for d in snap.days if d.date == day), None) if snap else None
            rows.append(
                PlanRow(
                    id=loc.id,
                    name=loc.name,
                    kind=loc.kind,
                    region=loc.region,
                    day=found,
                    danger=danger_for(avy.get(loc.id), day),
                )
            )
        response.headers["Cache-Control"] = CACHE
        return PlanOut(
            date=day, dates=[PlanDate(date=d, label=labels[d]) for d in dates], rows=rows
        )

    @router.get("/locations/{location_id}")
    def location(location_id: str, conn: Conn, request: Request) -> Response:
        """The latest snapshot, sent as stored (gzipped JSON)."""
        row = conn.execute(
            "SELECT run_id, doc_gz FROM snapshots WHERE location_id = ? "
            "ORDER BY run_id DESC LIMIT 1",
            (location_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"no forecast for {location_id!r}")
        etag = f'"{row["run_id"]}"'
        headers = {"ETag": etag, "Cache-Control": CACHE, "Vary": "Accept-Encoding"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        body: bytes = row["doc_gz"]
        if "gzip" in request.headers.get("accept-encoding", ""):
            headers["Content-Encoding"] = "gzip"
        else:
            body = gzip.decompress(body)
        return Response(body, media_type="application/json", headers=headers)

    @router.get("/locations/{location_id}/trend", response_model=TrendOut)
    def trend(
        location_id: str, conn: Conn, request: Request, runs: int = Query(10, ge=1, le=40)
    ) -> TrendOut:
        if service.get_location(conn, location_id) is None:
            raise HTTPException(404, f"unknown location {location_id!r}")
        # Every run stores the consensus both ways, so the trend follows the headline
        # depth method with no step on the day it changes.
        source = headline_source(request.app.state.forecast_config)
        rows = conn.execute(
            "SELECT run_id, issued_at, target_date, snow_cm FROM forecast_daily "
            "WHERE location_id = ? AND source = ? AND run_id IN ("
            "  SELECT DISTINCT run_id FROM forecast_daily WHERE location_id = ? "
            "  ORDER BY run_id DESC LIMIT ?"
            ") ORDER BY run_id, target_date",
            (location_id, source, location_id, runs),
        ).fetchall()
        by_run: dict[int, TrendRun] = {}
        for r in rows:
            tr = by_run.setdefault(
                r["run_id"],
                TrendRun(run_id=r["run_id"], issued_at=r["issued_at"], next5_cm=None, daily={}),
            )
            tr.daily[r["target_date"]] = r["snow_cm"]
        for tr in by_run.values():
            start = date.fromisoformat(min(tr.daily)) if tr.daily else None
            if start is not None:
                window = [(start + timedelta(days=i)).isoformat() for i in range(5)]
                vals = [tr.daily.get(d) for d in window]
                tr.next5_cm = (
                    None if any(v is None for v in vals) else round(sum(v or 0 for v in vals), 1)
                )
        return TrendOut(location_id=location_id, runs=list(by_run.values()))

    @router.get("/locations/{location_id}/verification", response_model=VerificationOut)
    def scorecard(location_id: str, conn: Conn, request: Request) -> VerificationOut:
        """Next-day forecasts against the snow station, per source."""
        loc = service.get_location(conn, location_id)
        if loc is None:
            raise HTTPException(404, f"unknown location {location_id!r}")
        cfg = request.app.state.forecast_config
        return verification(
            conn, loc, swe_ratio=cfg.verify_swe_ratio, headline=headline_source(cfg)
        )

    @router.get("/locations/{location_id}/nearby", response_model=NearbyOut)
    def nearby(location_id: str, conn: Conn, request: Request, response: Response) -> NearbyOut:
        """The closest snow stations and recent field reports (local files only)."""
        loc = service.get_location(conn, location_id)
        if loc is None:
            raise HTTPException(404, f"unknown location {location_id!r}")
        settings: Settings = request.app.state.settings
        mid = loc.band("mid")

        def km(lat: float, lon: float) -> float:
            return round(haversine_km(mid.lat, mid.lon, lat, lon), 1)

        st = _cached(_stations_cache, settings.stations_path, stations.read)
        near = sorted(
            (
                NearbyStation(station=s, distance_km=d)
                for s in (st.stations if st else [])
                if (d := km(s.lat, s.lon)) <= NEARBY_KM
            ),
            key=lambda x: x.distance_km,
        )
        obs = _cached(_obs_cache, settings.obs_path, observations.read)
        reports = []
        for f in obs.features if obs else []:
            xy = f.geometry.get("coordinates") or []
            if len(xy) >= 2 and (d := km(float(xy[1]), float(xy[0]))) <= NEARBY_KM:
                reports.append(NearbyReport(report=f.properties, distance_km=d))
        reports.sort(key=lambda x: x.report.time, reverse=True)
        response.headers["Cache-Control"] = CACHE
        return NearbyOut(
            location_id=loc.id,
            radius_km=NEARBY_KM,
            stations_at=st.generated_at if st else None,
            stations=near[:NEARBY_STATIONS],
            reports_at=obs.generated_at if obs else None,
            reports_days=obs.days if obs else None,
            reports=reports[:NEARBY_REPORTS],
        )

    @router.get("/status", response_model=StatusOut)
    def status(conn: Conn, request: Request) -> StatusOut:
        settings: Settings = request.app.state.settings
        sources = [
            SourceRow(
                source=r["source"],
                last_ok_at=r["last_ok_at"],
                last_error_at=r["last_error_at"],
                last_error=r["last_error"],
                calls_today=r["calls_today"] if r["day"] == _today() else 0,
                errors_today=r["errors_today"] if r["day"] == _today() else 0,
            )
            for r in conn.execute("SELECT * FROM source_status ORDER BY source")
        ]
        runs = [RunOut.model_validate(r) for r in repo.recent_runs(conn, 20)]
        weight = conn.execute(
            "SELECT COALESCE(SUM(api_weight), 0) FROM runs WHERE started_at >= ?", (_today(),)
        ).fetchone()[0]
        snaps = latest_snapshots(conn)
        ages = []
        for loc in service.list_locations(conn):
            snap = snaps.get(loc.id)
            ages.append(
                LocationAge(
                    id=loc.id,
                    name=loc.name,
                    generated_at=snap.generated_at if snap else None,
                    station=loc.snotel,
                    station_obs_time=snap.snotel.obs_time if snap and snap.snotel else None,
                    flags=len(snap.flags) if snap else 0,
                )
            )
        return StatusOut(
            sources=sources,
            runs=runs,
            weight_today=round(float(weight), 1),
            budget=settings.open_meteo_daily_budget,
            locations=ages,
        )

    @router.get("/runs", response_model=list[RunOut])
    def runs(conn: Conn, limit: int = Query(20, ge=1, le=200)) -> list[RunOut]:
        return [RunOut.model_validate(r) for r in repo.recent_runs(conn, limit)]

    return router
