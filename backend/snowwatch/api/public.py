"""Read-only endpoints for location data."""

from __future__ import annotations

import gzip
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from snowwatch import avalanche, observations, spots, stations
from snowwatch import avalanche_zones as zones
from snowwatch import ensembles as ens
from snowwatch.analysis.flags import SEVERITY, avalanche_flag
from snowwatch.api.auth import viewer_from
from snowwatch.api.models import (
    BandSummary,
    BestDay,
    CompareBand,
    CompareDay,
    CompareOut,
    CompareRow,
    ConcernOut,
    DangerChip,
    EnsemblesOut,
    EnsembleSystemOut,
    LocalServerOut,
    LocationAge,
    LocationSummary,
    MapCloudsLocation,
    MapCloudsOut,
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
    ShadowOut,
    SourceRow,
    StatusOut,
    TrendOut,
    TrendRun,
)
from snowwatch.api.ratelimit import client_key
from snowwatch.avalanche import AvalancheView
from snowwatch.avalanche_zones import ZonesOut
from snowwatch.config import get_forecast_config
from snowwatch.doc import BandOut, Snapshot
from snowwatch.geo import bbox, contains, haversine_km
from snowwatch.http import LOCAL_SUFFIX
from snowwatch.locations import service
from snowwatch.settings import Settings
from snowwatch.sources.openmeteo import SOURCE
from snowwatch.store import repo
from snowwatch.store.db import connect
from snowwatch.verify import VerificationOut, headline_source, verification

CACHE = "public, max-age=300, stale-while-revalidate=3600"

# The trend shows one run per this much time, so runs that mostly repeat the same
# model data (the forecast runs every 3 hours) don't flatten the chart. The slack
# lets a run that started a few minutes late still count as 6 hours on.
TREND_SPACING = timedelta(hours=6)
TREND_SLACK = timedelta(hours=1)


def _spaced_runs(conn: sqlite3.Connection, location_id: str, count: int) -> list[int]:
    """Up to `count` run ids for one location, newest first: the latest run, then each
    earlier run at least TREND_SPACING (less the slack) before the last one taken."""
    picked: list[int] = []
    last: datetime | None = None
    for r in conn.execute(
        "SELECT run_id, MIN(issued_at) AS issued_at FROM forecast_daily "
        "WHERE location_id = ? GROUP BY run_id ORDER BY run_id DESC",
        (location_id,),
    ):
        at = datetime.fromisoformat(r["issued_at"])
        if last is None or last - at >= TREND_SPACING - TREND_SLACK:
            picked.append(r["run_id"])
            last = at
            if len(picked) >= count:
                break
    return picked


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
NEARBY_PHOTO_REPORTS = 24
NEARBY_AREA_REPORTS = 16  # the Backcountry tab's recent observations
# The Webcams tab's photos: "near" a location within this distance and closer to it than to
# any other location; farther ones only if in the same avalanche zone (and NEARBY_KM).
NEAR_KM = 20.0
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


# Each avalanche zone's id, name, outline and its box, from the map's zones file.
ZoneIndex = list[tuple[str, str, dict[str, Any], tuple[float, float, float, float]]]
_zone_index_cache: dict[str, tuple[float, ZoneIndex | None]] = {}


def read_zone_index(path: Path) -> ZoneIndex | None:
    data = zones.read_zones(path)
    if data is None:
        return None
    out: ZoneIndex = []
    for f in data.get("features") or []:
        geom = f.get("geometry") if isinstance(f, dict) else None
        box = bbox(geom) if isinstance(geom, dict) else None
        if geom is None or box is None:
            continue
        doc = (f.get("properties") or {}).get("doc") or {}
        out.append((str(f.get("id")), str(doc.get("zone") or ""), geom, box))
    return out


def zone_at(index: ZoneIndex, lat: float, lon: float) -> str | None:
    """The id of the avalanche zone the point is in ("nac:3023"), or None."""
    for zid, _, geom, (w, s, e, n) in index:
        if w <= lon <= e and s <= lat <= n and contains(geom, lat, lon):
            return zid
    return None


def area_groups(
    loc_id: str,
    loc_zone: str | None,
    reports: list[tuple[NearbyReport, float, float]],
    others: list[tuple[str, float, float]],
    index: ZoneIndex,
    *,
    photos_only: bool = False,
) -> list[NearbyReport]:
    """The reports that belong to a location, each marked "near" or "zone", near first:
    for the Backcountry tab's recent observations and (`photos_only`) the Webcams tab's
    photos. `reports` come with their (lat, lon); `others` is every location's
    (id, lat, lon), to give a report to the closest one."""
    out = []
    for r, lat, lon in reports:
        if photos_only and not r.report.photos:
            continue
        nearest = min(others, key=lambda o: haversine_km(o[1], o[2], lat, lon), default=None)
        if r.distance_km <= NEAR_KM and (nearest is None or nearest[0] == loc_id):
            out.append(r.model_copy(update={"group": "near"}))
            continue
        zone = r.report.zone or zone_at(index, lat, lon)
        if loc_zone and zone == loc_zone:
            out.append(r.model_copy(update={"group": "zone"}))
    # Near ones first (each group stays newest first), so a cap never drops them for others.
    return sorted(out, key=lambda r: r.group != "near")


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


def _ensembles_out(conn: sqlite3.Connection, settings: Settings) -> EnsemblesOut:
    """Each system's source: in local mode, what the last run used (and since when), or
    whether its downloaded run is fresh before any run has; otherwise the public API."""
    now = datetime.now(UTC)
    mode = settings.ensemble_mode
    states = repo.ensemble_states(conn)
    systems = []
    for system in get_forecast_config().ensembles:
        run = ens.local_run(settings.open_meteo_data_dir, system)
        source, reason, since = "public", None, None
        if mode == "local":
            state = states.get(system)
            if state is not None:
                local, reason, since = state.local, state.reason, state.since
            else:
                reason = ens.stale_reason(settings.open_meteo_data_dir, system, now)
                local = reason is None
            source = "self-hosted" if local else "public"
        systems.append(
            EnsembleSystemOut(
                system=system,
                label=ens.label(system),
                source=source,
                run=run.isoformat(timespec="seconds") if run else None,
                age_h=round((now - run).total_seconds() / 3600, 1) if run else None,
                reason=reason,
                since=since,
            )
        )
    try:
        summary = repo.shadow_summary(conn, now=now)
    except sqlite3.OperationalError:  # not migrated yet
        summary = []
    shadow = [ShadowOut(label=ens.label(r.system), **vars(r)) for r in summary]
    return EnsemblesOut(mode=mode, systems=systems, shadow=shadow)


def nearby_at(
    settings: Settings,
    lat: float,
    lon: float,
    *,
    location_id: str,
    loc_zone: str | None = None,
    others: list[tuple[str, float, float]] | None = None,
) -> NearbyOut:
    """The closest snow stations and recent field reports around a point (local files
    only): a saved location's mid band, or a spot. `loc_zone`: its avalanche zone, when
    known ("nac:3023"), else looked up by point; `others`: every saved location's
    (id, lat, lon), so a report near several goes to the closest."""

    def km(p_lat: float, p_lon: float) -> float:
        return round(haversine_km(lat, lon, p_lat, p_lon), 1)

    st = _cached(_stations_cache, settings.stations_path, stations.read)
    near = sorted(
        (
            NearbyStation(station=s, distance_km=d)
            for s in (st.stations if st else [])
            if (d := km(s.lat, s.lon)) <= NEARBY_KM
        ),
        key=lambda x: x.distance_km,
    )
    obs = observations.merge(
        _cached(_obs_cache, settings.obs_path, observations.read),
        _cached(_obs_cache, settings.nwac_obs_path, observations.read),
    )
    located = []
    for f in obs.features if obs else []:
        xy = f.geometry.get("coordinates") or []
        if len(xy) >= 2 and (d := km(float(xy[1]), float(xy[0]))) <= NEARBY_KM:
            rep = NearbyReport(report=f.properties, distance_km=d)
            located.append((rep, float(xy[1]), float(xy[0])))
    located.sort(key=lambda x: x[0].report.time, reverse=True)
    reports = [r for r, _, _ in located]
    # The Webcams tab: near this place, or elsewhere in its avalanche zone.
    index = _cached(_zone_index_cache, settings.zones_path, read_zone_index) or []
    if loc_zone is None:
        loc_zone = zone_at(index, lat, lon)
    zone_name = next((name for zid, name, _, _ in index if zid == loc_zone and name), None)
    area = area_groups(location_id, loc_zone, located, others or [], index)
    photos = [r for r in area if r.report.photos]
    if zone_name is None:
        zone_name = next((r.report.region for r in area if r.group == "zone"), None)
    return NearbyOut(
        location_id=location_id,
        radius_km=NEARBY_KM,
        stations_at=st.generated_at if st else None,
        stations=near[:NEARBY_STATIONS],
        reports_at=obs.generated_at if obs else None,
        reports_days=obs.days if obs else None,
        reports=reports[:NEARBY_REPORTS],
        photo_reports=photos[:NEARBY_PHOTO_REPORTS],
        area_reports=area[:NEARBY_AREA_REPORTS],
        near_km=NEAR_KM,
        zone_name=zone_name or None,
    )


# Each avalanche zone's time zone and forecast, from the map's zones file.
_zone_docs_cache: dict[str, tuple[float, dict[str, tuple[str | None, Any]] | None]] = {}


def _read_zone_docs(path: Path) -> dict[str, tuple[str | None, Any]] | None:
    data = zones.read_zones(path)
    if data is None:
        return None
    return {
        str(f.get("id")): (
            (f.get("properties") or {}).get("tz"),
            (f.get("properties") or {}).get("doc"),
        )
        for f in data.get("features") or []
        if isinstance(f, dict)
    }


def zone_view(settings: Settings, zone_id: str, now: datetime) -> AvalancheView | None:
    """An avalanche zone's forecast as the map shows it, with expiry applied at `now`."""
    docs = _cached(_zone_docs_cache, settings.zones_path, _read_zone_docs) or {}
    hit = docs.get(zone_id)
    if hit is None:
        return None
    try:
        doc = avalanche.AvalancheDoc.model_validate(hit[1])
    except ValueError:
        return None
    return avalanche.view(zone_id, doc, now, avalanche.safe_zone(hit[0]))


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def make_router() -> APIRouter:
    router = APIRouter(prefix="/api")
    _snapshots.clear()  # a new app may point at a different database
    _zones_cache.clear()
    _stations_cache.clear()
    _obs_cache.clear()
    _zone_docs_cache.clear()

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

    @router.get("/map/clouds", response_model=MapCloudsOut)
    def map_clouds(conn: Conn, response: Response) -> MapCloudsOut:
        """Every location's cloud layers: the map's 3D clouds."""
        snaps = latest_snapshots(conn)
        out = []
        for loc in service.list_locations(conn):
            snap = snaps.get(loc.id)
            if snap is None or snap.clouds is None:
                continue
            mid = loc.band("mid")
            out.append(
                MapCloudsLocation(
                    id=loc.id,
                    name=loc.name,
                    lat=mid.lat,
                    lon=mid.lon,
                    base_m=loc.band("base").elev_m,
                    summit_m=loc.band("summit").elev_m,
                    generated_at=snap.generated_at,
                    clouds=snap.clouds,
                )
            )
        response.headers["Cache-Control"] = CACHE
        return MapCloudsOut(locations=out)

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

    @router.get("/compare", response_model=CompareOut)
    def compare(conn: Conn, response: Response) -> CompareOut:
        """Every location's next 10 days at each band, for ranking them on Compare."""
        snaps = latest_snapshots(conn)
        rows = []
        for loc in service.list_locations(conn):
            snap = snaps.get(loc.id)
            if snap is None:
                continue
            rows.append(CompareRow(id=loc.id, bands=[_compare_band(b) for b in snap.bands]))
        response.headers["Cache-Control"] = CACHE
        return CompareOut(rows=rows)

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
        picked = _spaced_runs(conn, location_id, runs)
        marks = ",".join("?" * len(picked))
        rows = conn.execute(
            "SELECT run_id, issued_at, target_date, snow_cm FROM forecast_daily "
            f"WHERE location_id = ? AND source = ? AND run_id IN ({marks}) "
            "ORDER BY run_id, target_date",
            (location_id, source, *picked),
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
            conn,
            loc,
            swe_ratio=cfg.verify_swe_ratio,
            headline=headline_source(cfg),
            snowfall_cm_per_mm=cfg.snowfall_cm_per_mm,
            settled_ratio=cfg.verify_settled_ratio,
        )

    @router.get("/locations/{location_id}/nearby", response_model=NearbyOut)
    def nearby(location_id: str, conn: Conn, request: Request, response: Response) -> NearbyOut:
        """The closest snow stations and recent field reports (local files only)."""
        loc = service.get_location(conn, location_id)
        if loc is None:
            raise HTTPException(404, f"unknown location {location_id!r}")
        mid = loc.band("mid")
        avy = loc.avy
        zone = f"nac:{avy.zone_id}" if avy and avy.provider == "nac" and avy.zone_id else None
        others = [
            (o.id, o.band("mid").lat, o.band("mid").lon) for o in service.list_locations(conn)
        ]
        response.headers["Cache-Control"] = CACHE
        return nearby_at(
            request.app.state.settings,
            mid.lat,
            mid.lon,
            location_id=loc.id,
            loc_zone=zone,
            others=others,
        )

    @router.get("/spot")
    def spot(
        request: Request,
        lat: float = Query(ge=-90, le=90),
        lon: float = Query(ge=-180, le=180),
        early: bool = False,
    ) -> Response:
        """A full forecast for any point in the US or Canada, made now (snowwatch/spots.py):
        the snapshot document a saved location has, with `spot` set. Gzipped like
        /locations/{id}. 422 outside the US and Canada; 503 without a self-hosted
        Open-Meteo server or while it can't answer; 429 past a visitor's limit.

        `early=1`: the map's spot panel opened on the point, so start it now if that costs
        nothing (SpotService.early; the signed-in owner has no early allowance to keep to);
        204 when it's skipped or fails, never an error."""
        settings: Settings = request.app.state.settings
        if not settings.local_open_meteo:
            raise HTTPException(503, "forecasts anywhere need a self-hosted Open-Meteo server")
        svc: spots.SpotService = request.app.state.spots
        if early:
            try:
                owner = viewer_from(request).is_owner
                got = svc.early(lat, lon, client_key(request), owner=owner)
            except (spots.OutsideCoverage, spots.SpotUnavailable):
                got = None
            if got is None:
                return Response(status_code=204, headers={"Cache-Control": "no-store"})
            return _spot_response(got, request)
        try:
            built = svc.get(lat, lon, client_key(request))
        except spots.OutsideCoverage as e:
            raise HTTPException(422, str(e)) from e
        except spots.SpotUnavailable as e:
            raise HTTPException(
                503,
                "the forecast server isn't answering; try again in a minute",
                headers={"Retry-After": "30"},
            ) from e
        except spots.SpotBusy as e:
            raise HTTPException(
                429 if e.visitor else 503, str(e), headers={"Retry-After": str(round(e.retry_s))}
            ) from e
        return _spot_response(built, request)

    @router.get("/spot/nearby", response_model=NearbyOut)
    def spot_nearby(
        request: Request,
        response: Response,
        lat: float = Query(ge=-90, le=90),
        lon: float = Query(ge=-180, le=180),
    ) -> NearbyOut:
        """A spot's Observed and Backcountry extras: the closest snow stations, recent field
        reports, and the avalanche zone it's in with its current forecast (local files
        only, no forecast is made)."""
        settings: Settings = request.app.state.settings
        lat, lon = spots.round_point(lat, lon)
        index = _cached(_zone_index_cache, settings.zones_path, read_zone_index) or []
        zone = zone_at(index, lat, lon)
        out = nearby_at(settings, lat, lon, location_id=spots.spot_id(lat, lon), loc_zone=zone)
        out.zone_id = zone
        out.avalanche = zone_view(settings, zone, datetime.now(UTC)) if zone else None
        response.headers["Cache-Control"] = "public, max-age=300"
        return out

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
        try:
            usage = repo.usage_today(conn)
        except sqlite3.OperationalError:  # the worker hasn't migrated yet
            usage = repo.Usage()
        local = None
        if settings.local_open_meteo:
            row = conn.execute(
                "SELECT * FROM source_status WHERE source = ?", (f"{SOURCE}{LOCAL_SUFFIX}",)
            ).fetchone()
            ok_at, err_at = (row["last_ok_at"], row["last_error_at"]) if row else (None, None)
            latency = usage.local_latency_s
            local = LocalServerOut(
                ok=ok_at is not None and (err_at is None or ok_at >= err_at),
                last_ok_at=ok_at,
                last_error_at=err_at,
                last_error=row["last_error"] if row else None,
                latency_s=None if latency is None else round(latency, 2),
                requests_today=usage.local_requests,
                fallbacks_today=usage.fallbacks,
            )
        ensembles = _ensembles_out(conn, settings) if settings.local_open_meteo else None
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
            weight_today=round(usage.public_weight, 1),
            budget=settings.open_meteo_daily_budget,
            locations=ages,
            local=local,
            ensembles=ensembles,
        )

    @router.get("/runs", response_model=list[RunOut])
    def runs(conn: Conn, limit: int = Query(20, ge=1, le=200)) -> list[RunOut]:
        return [RunOut.model_validate(r) for r in repo.recent_runs(conn, limit)]

    return router


def _spot_response(built: spots.Built, request: Request) -> Response:
    """A built spot as sent: gzipped when the browser takes it, with its ETag."""
    headers = {
        "ETag": built.etag,
        "Cache-Control": "public, max-age=600",
        "Vary": "Accept-Encoding",
    }
    if request.headers.get("if-none-match") == built.etag:
        return Response(status_code=304, headers=headers)
    body = built.gz
    if "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
    else:
        body = gzip.decompress(body)
    return Response(body, media_type="application/json", headers=headers)


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _compare_band(band: BandOut) -> CompareBand:
    """A band's days as the Compare page counts them (lib/compare.ts dayCells)."""
    dates = list(dict.fromkeys(p.date for p in band.periods))[:10]
    fl_by_date: dict[str, list[float]] = {}
    for t, level in zip(band.hourly.t, band.hourly.fl_m, strict=False):
        if level is not None:
            fl_by_date.setdefault(t[:10], []).append(level)
    days = []
    for d in dates:
        ps = [p for p in band.periods if p.date == d]
        tmax = [p.tmax_c for p in ps if p.tmax_c is not None]
        tmin = [p.tmin_c for p in ps if p.tmin_c is not None]
        gust = [p.gust_max_kmh for p in ps if p.gust_max_kmh is not None]
        fl = fl_by_date.get(d, [])
        days.append(
            CompareDay(
                date=d,
                snow_cm=round(sum(p.snow_cm or 0 for p in ps), 2),
                rain_mm=round(sum(p.rain_mm or 0 for p in ps), 2),
                tmax_c=max(tmax) if tmax else None,
                tmin_c=min(tmin) if tmin else None,
                gust_kmh=max(gust) if gust else None,
                fl_min_m=min(fl) if fl else None,
                slr=_mean([p.slr for p in ps if p.slr is not None]),
                cloud=_mean([p.cloud_mean for p in ps if p.cloud_mean is not None]),
            )
        )
    return CompareBand(band=band.band, elev_m=band.elev_m, days=days)
