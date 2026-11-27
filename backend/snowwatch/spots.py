"""Forecasts anywhere: a full forecast for any point in the US or Canada, built on request
(docs/OPEN-METEO-PLAN.md, milestone 2).

A spot is a transient `Location`: its three bands share the tapped point and differ only
in elevation, chosen from the terrain around it (`choose_bands`). Its forecasts come
from the self-hosted Open-Meteo server only (no public fallback: without the server a
forecast per tap would spend the public daily limit in minutes), through the same
request builders and `build_snapshot` as a saved location. It has no snow station, no
trend and no scorecard, and nothing about it is stored except its ensembles, which are
shared per 0.25° cell for a few hours (`spot_ensembles`).

`SpotService` is what the API holds: a small cache of built spots and the limits that
bound the server's work (per visitor, at once, per hour for the whole site).
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import logging
import math
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from snowwatch.analysis.build import build_snapshot
from snowwatch.api.ratelimit import RateLimiter
from snowwatch.config import ForecastConfig
from snowwatch.doc import Snapshot, SpotInfo, SpotNearest, SpotPeak
from snowwatch.geo import bbox, bearing_deg, compass, contains, destination, edge_km, haversine_km
from snowwatch.http import Fetcher, FetchError
from snowwatch.inputs import inputs_from_responses
from snowwatch.locations.resolve import MID_SHARE
from snowwatch.models import Band, BandName, Location
from snowwatch.peaks import Peak, peaks_near
from snowwatch.sources import nws
from snowwatch.sources.base import Request, fetch
from snowwatch.sources.openmeteo import (
    blend_request,
    clouds_request,
    elevation_request,
    ensemble_request,
    merge_models,
    multimodel_request,
    upper_air_request,
)
from snowwatch.store import repo
from snowwatch.store.db import connect

if TYPE_CHECKING:
    from snowwatch.settings import Settings

log = logging.getLogger("snowwatch.spots")

# The terrain sampled around a point: rings at these distances, this many bearings each.
RING_KM = (1.0, 2.5)
BEARINGS = 12
NEAR_EDGE_M = 100.0  # within this of the ring's highest (lowest) ground: the top (bottom)
MIN_GAP_M = 150.0  # bands at least this far apart
FLAT_M = 300.0  # flat ground: bands this far below and above the point
PEAK_KM = 0.5  # a named peak this close names the spot ("Mount Stuart")…
PEAK_NEAR_KM = 6.0  # …and one this close places it ("1.2 km NE of Mount Stuart")
PEAKS_WAIT_S = 3.0  # the label tiles' peaks are waited for this long, at most
NAME_LOCATION_KM = 40.0  # "6 km NE of Crystal Mountain" from a saved location this close
NEAREST_KM = 100.0  # SpotInfo.nearest
BORDER_KM = 3.0  # a point this close to the simplified US/Canada outline counts as inside
ENS_CELL_DEG = 0.25  # spot ensembles are fetched per cell of this size…
ENS_STEP_M = 100.0  # …and step of elevation
ALERTS_CELL_DEG = 0.1  # NWS alerts are kept per cell of this size…
ALERTS_TTL_S = 600.0  # …for this long
KEY_DIGITS = 3  # spots are built at the point rounded to ~100 m, which is also the cache key
LOCAL_TIMEOUT_S = 60.0  # a cold area's first summit request took 52 s

COVERAGE = "Forecasts anywhere cover the US and Canada"
GEOHASH = "0123456789bcdefghjkmnpqrstuvwxyz"


class OutsideCoverage(ValueError):
    """The point is outside the US and Canada (422)."""


class SpotUnavailable(RuntimeError):
    """No self-hosted server, or it can't answer now (503)."""


class SpotBusy(RuntimeError):
    """Over a limit: this visitor's (429) or the site's (503). Retry after `retry_s`."""

    def __init__(self, message: str, retry_s: float, *, visitor: bool) -> None:
        super().__init__(message)
        self.retry_s = retry_s
        self.visitor = visitor


# --- bands from the terrain ---------------------------------------------------------------


@dataclass(frozen=True)
class Bands:
    base: float
    mid: float
    summit: float
    method: Literal["top", "bottom", "slope", "flat"]
    band: BandName  # the band that holds the point


def ring_points(lat: float, lon: float) -> list[tuple[float, float]]:
    """The point, then BEARINGS samples on each ring of RING_KM."""
    pts = [(lat, lon)]
    for km in RING_KM:
        pts += [destination(lat, lon, i * 360 / BEARINGS, km) for i in range(BEARINGS)]
    return pts


def choose_bands(h: float, ring: Iterable[float]) -> Bands:
    """Base, mid and summit from the point's elevation `h` and the ring samples'.

    Near the top (h ≥ highest − 100 m) the point is the summit, the lowest ground the
    base and mid is 60 % up; near the bottom the point is the base and the highest
    ground the summit; otherwise the point is mid, between the two. Bands stay at least
    150 m apart; on flat ground (less than 300 m of relief) they are 300 m below and above.
    """
    samples = list(ring)
    lo, hi = min([h, *samples]), max([h, *samples])
    if hi - lo < 2 * MIN_GAP_M:
        return Bands(h - FLAT_M, h, h + FLAT_M, "flat", "mid")
    if h >= hi - NEAR_EDGE_M:
        base, summit = lo, h
        mid = base + MID_SHARE * (summit - base)
        method: Literal["top", "bottom", "slope"] = "top"
        band: BandName = "summit"
    elif h <= lo + NEAR_EDGE_M:
        base, summit = h, hi
        mid = base + MID_SHARE * (summit - base)
        method, band = "bottom", "base"
    else:
        base, mid, summit = min(lo, h - MIN_GAP_M), h, max(hi, h + MIN_GAP_M)
        method, band = "slope", "mid"
    if method != "slope":  # keep mid clear of both ends (the vertical is ≥ 300 m)
        mid = min(max(mid, base + MIN_GAP_M), summit - MIN_GAP_M)
    return Bands(round(base), round(mid), round(summit), method, band)


# --- where: country and name ---------------------------------------------------------------

Border = tuple[str, dict[str, Any], tuple[float, float, float, float]]
_borders: dict[str, tuple[float, list[Border]]] = {}


def load_borders(path: Path) -> list[Border]:
    """Each polygon of `config/borders.geojson` with its country and box, read once per
    change of the file."""
    mtime = path.stat().st_mtime
    hit = _borders.get(str(path))
    if hit is None or hit[0] != mtime:
        out: list[Border] = []
        for f in json.loads(path.read_text())["features"]:
            country = f["properties"]["country"]
            g = f["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            for poly in polys:
                geom = {"type": "Polygon", "coordinates": poly}
                box = bbox(geom)
                if box is not None:
                    out.append((country, geom, box))
        hit = (mtime, out)
        _borders[str(path)] = hit
    return hit[1]


def country_at(borders: list[Border], lat: float, lon: float) -> Literal["US", "CA"] | None:
    """US or CA for a point inside either outline (or within BORDER_KM of one: the
    outline is simplified), else None."""
    for country, geom, (w, s, e, n) in borders:
        if w <= lon <= e and s <= lat <= n and contains(geom, lat, lon):
            return "US" if country == "US" else "CA"
    margin = BORDER_KM / 80  # degrees, generously
    best: tuple[float, str] | None = None
    for country, geom, (w, s, e, n) in borders:
        slack = margin / max(0.2, math.cos(math.radians(lat)))
        if w - slack <= lon <= e + slack and s - margin <= lat <= n + margin:
            d = edge_km(geom, lat, lon)
            if d <= BORDER_KM and (best is None or d < best[0]):
                best = (d, country)
    if best is None:
        return None
    return "US" if best[1] == "US" else "CA"


_peaks: dict[str, tuple[float, list[Peak]]] = {}


def read_peaks(path: Path) -> list[Peak]:
    """Named peaks in the map's ski file (data/osm/ski.geojson: the areas around saved
    locations), read once per change of the file; none when it's missing."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    hit = _peaks.get(str(path))
    if hit is None or hit[0] != mtime:
        out: list[Peak] = []
        try:
            features = json.loads(path.read_text()).get("features") or []
        except (OSError, ValueError):
            features = []
        for f in features:
            props = f.get("properties") or {}
            geom = f.get("geometry") or {}
            if props.get("kind") == "peak" and props.get("name") and geom.get("type") == "Point":
                lon, lat = geom["coordinates"][:2]
                out.append((str(props["name"]), float(lat), float(lon)))
        hit = (mtime, out)
        _peaks[str(path)] = hit
    return hit[1]


def nearest_location(
    locations: Iterable[Location], lat: float, lon: float
) -> tuple[Location, float] | None:
    """The saved location whose mid band is nearest, with the distance in km."""
    best: tuple[Location, float] | None = None
    for loc in locations:
        mid = loc.band("mid")
        d = haversine_km(mid.lat, mid.lon, lat, lon)
        if best is None or d < best[1]:
            best = (loc, d)
    return best


def coords_label(lat: float, lon: float) -> str:
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    return f"{abs(lat):.3f}° {ns}, {abs(lon):.3f}° {ew}"


def nearest_peak(peaks: Iterable[Peak], lat: float, lon: float) -> tuple[Peak, float] | None:
    """The nearest named peak and its distance (km)."""
    return min(
        ((pk, haversine_km(lat, lon, pk[1], pk[2])) for pk in peaks),
        key=lambda x: x[1],
        default=None,
    )


def km_label(km: float) -> str:
    """600 m, 1.2 km, 14 km."""
    if km < 1:
        return f"{max(100, round(km * 10) * 100):.0f} m"
    return f"{km:.1f} km" if km < 10 else f"{km:.0f} km"


def spot_name(
    lat: float, lon: float, peaks: Iterable[Peak], nearest: tuple[Location, float] | None
) -> tuple[str, SpotPeak | None]:
    """The spot's name after the terrain: the nearest named peak within 0.5 km ("Mount
    Stuart"); else where it is from the nearest within 6 km ("1.2 km NE of Mount
    Stuart"); else from the nearest saved location within 40 km ("6 km NE of Crystal
    Mountain"); else the coordinates. With the peak it's named after, if any (the app
    words its distance in the viewer's units)."""
    found = nearest_peak(peaks, lat, lon)
    if found is not None and found[1] <= PEAK_NEAR_KM:
        (name, p_lat, p_lon), km = found
        if km <= PEAK_KM:
            return name, SpotPeak(name=name, km=round(km, 2), bearing=None)
        way = compass(bearing_deg(p_lat, p_lon, lat, lon))
        return f"{km_label(km)} {way} of {name}", SpotPeak(name=name, km=round(km, 2), bearing=way)
    if nearest is not None and nearest[1] <= NAME_LOCATION_KM:
        loc, km = nearest
        if km < 1:
            return f"Near {loc.name}", None
        mid = loc.band("mid")
        return f"{km:.0f} km {compass(bearing_deg(mid.lat, mid.lon, lat, lon))} of {loc.name}", None
    return coords_label(lat, lon), None


def geohash(lat: float, lon: float, precision: int = 7) -> str:
    """The standard geohash (7 characters: a cell of about 150 m)."""
    lat_r, lon_r = [-90.0, 90.0], [-180.0, 180.0]
    out: list[str] = []
    bits, ch, even = 0, 0, True
    while len(out) < precision:
        rng, v = (lon_r, lon) if even else (lat_r, lat)
        middle = (rng[0] + rng[1]) / 2
        ch <<= 1
        if v >= middle:
            ch |= 1
            rng[0] = middle
        else:
            rng[1] = middle
        even = not even
        bits += 1
        if bits == 5:
            out.append(GEOHASH[ch])
            bits, ch = 0, 0
    return "".join(out)


def spot_id(lat: float, lon: float) -> str:
    return "spot-" + geohash(lat, lon)


def spot_location(
    lat: float, lon: float, bands: Bands, country: Literal["US", "CA"], name: str
) -> Location:
    """The transient location a spot is built as (the time zone comes from the forecast)."""
    labels = {"base": "Lower", "mid": "Middle", "summit": "Upper"}
    labels[bands.band] = "This spot"
    links = (
        {"NWS forecast": f"https://forecast.weather.gov/MapClick.php?lat={lat:.3f}&lon={lon:.3f}"}
        if country == "US"
        else {"Mountain forecast (ECCC)": "https://weather.gc.ca/mountain_forecast/"}
    )
    elevs = {"base": bands.base, "mid": bands.mid, "summit": bands.summit}
    return Location(
        id=spot_id(lat, lon),
        name=name[:80],
        kind="backcountry",
        country=country,
        tz=None,
        bands=[
            Band(band=b, label=labels[b], lat=lat, lon=lon, elev_m=elevs[b])
            for b in ("base", "mid", "summit")
        ],
        links=links,
    )


def round_point(lat: float, lon: float) -> tuple[float, float]:
    """The point a spot is built at, and its cache key: ~100 m."""
    return round(lat, KEY_DIGITS), round(lon, KEY_DIGITS)


def ensemble_cell(lat: float, lon: float, elev_m: float) -> tuple[float, float, float, str]:
    """Where a spot's ensembles are asked for (the 0.25° cell's centre and the 100 m
    step), and the cache key for that."""
    c_lat = round(round(lat / ENS_CELL_DEG) * ENS_CELL_DEG, 2)
    c_lon = round(round(lon / ENS_CELL_DEG) * ENS_CELL_DEG, 2)
    step = round(elev_m / ENS_STEP_M) * ENS_STEP_M
    return c_lat, c_lon, step, f"{c_lat:g},{c_lon:g},{step:g}"


# --- building one ---------------------------------------------------------------------------


@dataclass
class EnsembleResult:
    responses: dict[str, Any] = field(default_factory=dict)  # ens_<system> → answer
    status: Literal["fresh", "cached", "allowance_spent", "unavailable"] = "unavailable"


@dataclass
class EnsemblePlan:
    """Which systems a spot fetches, and how (decided before anything is fetched, so the
    fetches can run at once): `fetch` maps each system to its request and whether it may
    fall back to the public API."""

    cell: str
    result: EnsembleResult
    fetch: dict[str, tuple[Request, bool]] = field(default_factory=dict)
    spent: bool = False


def plan_ensembles(
    fetcher: Fetcher,
    loc: Location,
    cfg: ForecastConfig,
    conn: sqlite3.Connection | None,
    *,
    now: datetime,
    spot_used: float,
) -> EnsemblePlan:
    """Each system's ensembles at the mid band: a nearby spot's within the cache time;
    else the self-hosted server's while its run is fresh (OPEN_METEO_ENSEMBLES=local,
    free); else the public API within the spots' daily allowance (`spot_used` is today's
    spot weight so far). The server's answers may fall back to the public API only while
    the allowance has room, which is set aside for them here."""
    mid = loc.band("mid")
    c_lat, c_lon, step, cell = ensemble_cell(mid.lat, mid.lon, mid.elev_m)
    sc = cfg.spots
    cached: dict[str, Any] = {}
    if conn is not None:
        try:
            cached = repo.spot_ensembles(conn, cell, now=now, max_age_h=sc.ensemble_cache_h)
        except sqlite3.Error:  # not migrated yet: no cache
            cached = {}
    plan = EnsemblePlan(cell, EnsembleResult())
    planned = spot_used
    for system in cfg.ensembles:
        req = ensemble_request(loc, system)
        if system in cached:
            plan.result.responses[req.name] = cached[system]
            continue
        params = req.params | {
            "latitude": f"{c_lat:g}",
            "longitude": f"{c_lon:g}",
            "elevation": f"{step:g}",
        }
        req = dataclasses.replace(req, params=params)
        room = planned + req.weight <= sc.ensemble_allowance
        if not fetcher.local_ensemble(system) and not room:
            plan.spent = True
            continue
        if room:
            planned += req.weight
        plan.fetch[system] = (req, room)
    return plan


def finish_ensembles(
    plan: EnsemblePlan,
    got: dict[str, Any],
    fetcher: Fetcher,
    cfg: ForecastConfig,
    conn: sqlite3.Connection | None,
    *,
    now: datetime,
) -> EnsembleResult:
    """The planned answers that came back (`got`, by system), kept for nearby spots, and
    what the spot says about its ensembles."""
    out = plan.result
    cached = bool(out.responses)
    for system, data in got.items():
        req, _ = plan.fetch[system]
        out.responses[req.name] = data
        if conn is None:
            continue
        source = "local" if system in fetcher.ensembles_local else "public"
        try:
            repo.put_spot_ensemble(
                conn,
                plan.cell,
                system,
                data,
                source,
                now=now,
                max_age_h=cfg.spots.ensemble_cache_h,
            )
        except sqlite3.Error as e:  # a busy or unmigrated database only costs the cache
            log.warning("spot ensembles not cached: %s", e)
    failed_public = any(not room for system, (_, room) in plan.fetch.items() if system not in got)
    if plan.spent or failed_public:
        out.status = "allowance_spent"
    elif got:
        out.status = "fresh"
    elif cached:
        out.status = "cached"
    return out


@dataclass
class SpotContext:
    """What a build reads besides the forecasts: the outlines, saved locations, peaks."""

    borders: list[Border]
    locations: list[Location]
    peaks: list[Peak]
    conn: sqlite3.Connection | None = None  # read-write: the ensemble cache
    spot_used: float = 0.0  # today's public weight for spots (the allowance)
    alerts: Callable[[float, float], Any] | None = None  # cached NWS alerts at a point
    # Named peaks round a point from the label tiles (snowwatch/peaks.py): every peak,
    # where `peaks` only has those round saved locations.
    tile_peaks: Callable[[float, float], list[Peak]] | None = None


def build_spot(
    fetcher: Fetcher,
    cfg: ForecastConfig,
    ctx: SpotContext,
    lat: float,
    lon: float,
    now: datetime,
    timings: dict[str, float] | None = None,
) -> Snapshot:
    """The forecast for one point. Raises OutsideCoverage or SpotUnavailable.

    The requests run at once, so a spot in an area the server hasn't read yet waits for
    the slowest of them, not for all of them in turn: the terrain, upper air, clouds and
    alerts first (they need only the point), then the blend, the multi-model forecast
    and the ensembles once the terrain has given the bands. The multi-model forecast and
    upper air are asked for one model each and joined (`merge_models`): the server reads
    one request's models in turn. `timings` gets each request's seconds (the API logs
    them)."""
    lat, lon = round_point(lat, lon)
    country = country_at(ctx.borders, lat, lon)
    if country is None:
        raise OutsideCoverage(COVERAGE)
    times = timings if timings is not None else {}
    errors: list[str] = []

    def timed(name: str, work: Callable[[], Any]) -> Callable[[], Any]:
        def run() -> Any:
            t0 = time.monotonic()
            try:
                return work()
            finally:
                times[name] = round(time.monotonic() - t0, 1)

        return run

    def optional(req: Request) -> Callable[[], Any]:
        return lambda: _optional(fetcher, req, errors)

    # The point's own requests don't depend on the bands' elevations, only on where it
    # is: a provisional location with the point's lat/lon builds them.
    here = spot_location(lat, lon, Bands(0, 1, 2, "flat", "mid"), country, "here")
    rich = bool(fetcher.local_url)  # always, for spots: they need the server
    # The label tiles' peaks, on a pool of their own: waited for only so long, and a slow
    # tile server must not hold the build up when it ends.
    peaks_f: Future[list[Peak]] | None = None
    if ctx.tile_peaks is not None:
        tile_peaks = ctx.tile_peaks
        peaks_f = _PEAKS_POOL.submit(timed("peaks", lambda: tile_peaks(lat, lon)))
    with ThreadPoolExecutor(max_workers=12, thread_name_prefix="spot") as pool:
        elev_f = pool.submit(
            timed(
                "elevation",
                lambda: fetch(
                    fetcher, elevation_request(ring_points(lat, lon)), allow_fallback=False
                ),
            )
        )
        upper_f = {
            m: pool.submit(timed(f"upper {m}", optional(upper_air_request(here, [m], rich=rich))))
            for m in cfg.upper_air_models(country)
        }
        side: dict[str, Future[Any]] = {}
        cloud_model = cfg.cloud_model(country)
        if cloud_model:
            side["clouds"] = pool.submit(
                timed("clouds", optional(clouds_request(here, cloud_model)))
            )
        if country == "US" and ctx.alerts is not None:
            alerts = ctx.alerts
            side["nws_alerts"] = pool.submit(timed("alerts", lambda: alerts(lat, lon)))
        try:
            elevs = [float(e) for e in elev_f.result()["elevation"]]
        except (FetchError, KeyError, TypeError, ValueError) as e:
            raise SpotUnavailable(f"terrain elevation unavailable: {e}") from e
        if len(elevs) != 1 + len(RING_KM) * BEARINGS:
            raise SpotUnavailable("terrain elevation unavailable: wrong number of values")
        bands = choose_bands(elevs[0], elevs[1:])
        near = nearest_location(ctx.locations, lat, lon)
        all_peaks = list(ctx.peaks)
        if peaks_f is not None:
            try:
                all_peaks += peaks_f.result(timeout=PEAKS_WAIT_S)
            except Exception as e:  # a name from elsewhere then; never the forecast's fault
                log.info("spot peaks unavailable: %s", e)
        name, peak = spot_name(lat, lon, all_peaks, near)
        loc = spot_location(lat, lon, bands, country, name)
        models = cfg.models_for(country)
        blend_f = pool.submit(
            timed(
                "blend", lambda: fetch(fetcher, blend_request(loc, rich=rich), allow_fallback=False)
            )
        )
        multi_f = {
            m: pool.submit(
                timed(
                    f"multi {m}",
                    partial(
                        fetch,
                        fetcher,
                        multimodel_request(loc, [m], rich=rich),
                        allow_fallback=False,
                    ),
                )
            )
            for m in models
        }
        plan = plan_ensembles(fetcher, loc, cfg, ctx.conn, now=now, spot_used=ctx.spot_used)
        ens_f = {
            system: pool.submit(
                timed(f"ens_{system}", partial(_ensemble, fetcher, req, room, errors))
            )
            for system, (req, room) in plan.fetch.items()
        }
        responses: dict[str, Any] = {}
        try:
            responses["blend"] = blend_f.result()
        except FetchError as e:
            raise SpotUnavailable(f"forecast unavailable: {e}") from e
        multi: dict[str, Any] = {}
        for m, f in multi_f.items():
            try:
                multi[m] = f.result()
            except FetchError as e:  # one model missing is tolerated, as in one request
                errors.append(f"multi {m}: {e}")
        if not multi:
            raise SpotUnavailable("forecast unavailable: no model answered")
        responses["multi"] = merge_models(multi)
        upper = {m: data for m, f in upper_f.items() if (data := f.result()) is not None}
        if upper:
            responses["upper"] = merge_models(upper)
        for name, f in side.items():
            try:
                data = f.result()
            except FetchError as e:
                errors.append(f"{name}: {e}")
                continue
            if data is not None:
                responses[name] = data
        got = {s: data for s, f in ens_f.items() if (data := f.result()) is not None}
    ens = finish_ensembles(plan, got, fetcher, cfg, ctx.conn, now=now)
    responses.update(ens.responses)
    inputs = inputs_from_responses(loc, responses, cfg, warnings=errors)
    snap, _ = build_snapshot(loc, inputs, cfg, now)
    snap.spot = SpotInfo(
        lat=lat,
        lon=lon,
        elev_m=round(elevs[0]),
        band=bands.band,
        method=bands.method,
        ensembles=ens.status,
        peak=peak,
        nearest=(
            SpotNearest(id=near[0].id, name=near[0].name, km=round(near[1], 1))
            if near is not None and near[1] <= NEAREST_KM
            else None
        ),
    )
    return snap


_PEAKS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="spot-peaks")


def _optional(fetcher: Fetcher, req: Request, errors: list[str]) -> Any | None:
    """An optional forecast from the server (upper air, clouds): a failure is a warning."""
    try:
        return fetch(fetcher, req, optional=True, allow_fallback=False)
    except FetchError as e:
        errors.append(f"{req.name}: {e}")
        return None


def _ensemble(fetcher: Fetcher, req: Request, room: bool, errors: list[str]) -> Any | None:
    """One system's ensembles; the public fallback only with room in the allowance."""
    try:
        return fetch(fetcher, req, optional=True, allow_fallback=room)
    except FetchError as e:
        errors.append(f"{req.name}: {e}")
        return None


# --- the service: cache and limits ------------------------------------------------------------


@dataclass(frozen=True)
class Built:
    """One built spot as the API sends it."""

    etag: str
    gz: bytes
    built_at: float  # the service clock


class SpotService:
    """Builds spots for the API, keeps the last few hundred, and bounds the work.

    Uncached builds: each visitor 8 at once then one per 15 s, at most 2 at a time, and
    about 600 an hour for the whole site. Cached ones: a lighter per-visitor limit. A
    built spot is kept `spots.cache_minutes` (the models update about hourly), keyed by
    the point rounded to ~100 m.
    """

    def __init__(
        self,
        cfg: ForecastConfig,
        build: Callable[[float, float], Snapshot],
        *,
        clock: Callable[[], float] = time.monotonic,
        max_builds: int = 2,
        wait_s: float = 20.0,
    ) -> None:
        self.cfg = cfg
        self._build = build
        self.clock = clock
        self.ttl_s = cfg.spots.cache_minutes * 60
        self.max_entries = cfg.spots.cache_entries
        self._cache: OrderedDict[tuple[float, float], Built] = OrderedDict()
        self._lock = threading.Lock()
        self._builds = threading.BoundedSemaphore(max_builds)
        self._wait_s = wait_s
        self._key_locks: dict[tuple[float, float], threading.Lock] = {}
        self.visitor = RateLimiter(rate=1 / 15, burst=8, clock=clock)
        self.hits = RateLimiter(rate=2, burst=60, clock=clock)
        self.site = RateLimiter(rate=600 / 3600, burst=100, clock=clock)
        # Early builds (the map starts one when its spot panel opens, before "Full forecast
        # here"): an allowance of their own, so tapping around never uses up a visitor's
        # builds for the button itself.
        self.early_limit = RateLimiter(rate=1 / 10, burst=6, clock=clock)
        self.down_until = 0.0  # after the server failed, answer 503 at once for a while
        self.down_reason = ""

    def cached(self, lat: float, lon: float) -> Built | None:
        key = round_point(lat, lon)
        with self._lock:
            hit = self._cache.get(key)
            if hit is None:
                return None
            if self.clock() - hit.built_at > self.ttl_s:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return hit

    def _store(self, key: tuple[float, float], snap: Snapshot) -> Built:
        body = snap.model_dump_json().encode()
        built = Built(
            etag='"' + hashlib.sha256(body).hexdigest()[:16] + '"',
            gz=gzip.compress(body, 6),
            built_at=self.clock(),
        )
        with self._lock:
            self._cache[key] = built
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
        return built

    def early(self, lat: float, lon: float, visitor: str, *, owner: bool = False) -> Built | None:
        """Start a spot before it's asked for (the map's spot panel opened on it), so the
        button finds it made or on its way. Only when it costs nobody anything: within the
        early allowance (not for the signed-in owner) and the site's, with a build slot
        free and the point not already being made; otherwise None at once. Raises
        OutsideCoverage, SpotUnavailable."""
        hit = self.cached(lat, lon)
        if hit is not None:
            return hit
        if self.clock() < self.down_until:
            return None
        if not (owner or self.early_limit.allow(visitor)) or not self.site.allow("site"):
            return None
        key = round_point(lat, lon)
        with self._lock:
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        if not key_lock.acquire(blocking=False):
            return None  # already being made
        try:
            if not self._builds.acquire(blocking=False):
                return None
            try:
                snap = self._build(*key)
            except SpotUnavailable as e:
                self.down_until = self.clock() + 30
                self.down_reason = str(e)
                raise
            finally:
                self._builds.release()
            return self._store(key, snap)
        finally:
            key_lock.release()
            with self._lock:
                if self._key_locks.get(key) is key_lock:
                    self._key_locks.pop(key, None)

    def get(self, lat: float, lon: float, visitor: str) -> Built:
        """A spot, from the cache or built now. Raises SpotBusy, OutsideCoverage,
        SpotUnavailable."""
        hit = self.cached(lat, lon)
        if hit is not None:
            if not self.hits.allow(visitor):
                raise SpotBusy("too many requests; try again in a minute", 30, visitor=True)
            return hit
        if self.clock() < self.down_until:
            raise SpotUnavailable(self.down_reason)
        if not self.visitor.allow(visitor):
            raise SpotBusy("too many new spots; try again in a few seconds", 15, visitor=True)
        if not self.site.allow("site"):
            raise SpotBusy(
                "the site is making a lot of forecasts; try again soon", 60, visitor=False
            )
        key = round_point(lat, lon)
        with self._lock:
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        with key_lock:  # one build per point; others wait for it and take the result
            try:
                hit = self.cached(lat, lon)
                if hit is not None:
                    return hit
                if not self._builds.acquire(timeout=self._wait_s):
                    raise SpotBusy("busy making other forecasts; try again", 10, visitor=False)
                try:
                    snap = self._build(*key)
                except SpotUnavailable as e:
                    self.down_until = self.clock() + 30
                    self.down_reason = str(e)
                    raise
                finally:
                    self._builds.release()
                return self._store(key, snap)
            finally:
                with self._lock:
                    self._key_locks.pop(key, None)


def make_service(
    settings: Settings,
    cfg: ForecastConfig,
    make_fetcher: Callable[[], Fetcher],
    label_tile: Callable[[int, int, int], bytes | None] | None = None,
) -> SpotService:
    """The API's SpotService: builds with a fresh fetcher each time (the self-hosted server,
    no public fallback for forecasts), records public use under the spots' ledger row, and
    keeps NWS alerts per 0.1° cell for 10 minutes."""
    from snowwatch.locations import service as locations
    from snowwatch.tiles import TileCache

    alerts_cache: dict[tuple[int, int], tuple[float, Any]] = {}
    # The map's label tiles, through the server's tile cache (kept on disk, so an area's
    # peaks are fetched once): the peaks to name spots after.
    if label_tile is None:
        tiles = TileCache(
            settings.tiles_dir, settings.user_agent, max_bytes=settings.tiles_max_mb * 1_000_000
        )

        def label_tile(z: int, x: int, y: int) -> bytes | None:
            got = tiles.get("labels", z, x, y)
            return got[0] if got else None

    get_tile = label_tile

    alerts_lock = threading.Lock()

    def build(lat: float, lon: float) -> Snapshot:
        if not settings.local_open_meteo:
            raise SpotUnavailable("forecasts anywhere need a self-hosted Open-Meteo server")
        now = datetime.now(UTC)
        conn: sqlite3.Connection | None = None
        locs: list[Location] = []
        spot_used = 0.0
        if settings.database.exists():
            conn = connect(settings.database)
            try:
                locs = locations.list_locations(conn)
                spot_used = repo.usage_today(conn, now).by_host.get(repo.SPOT_HOST, 0.0)
            except sqlite3.Error:  # not migrated yet
                pass
        with make_fetcher() as fetcher:

            def alerts(a_lat: float, a_lon: float) -> Any:
                cell = (round(a_lat / ALERTS_CELL_DEG), round(a_lon / ALERTS_CELL_DEG))
                t = time.monotonic()
                with alerts_lock:
                    hit = alerts_cache.get(cell)
                    if hit is not None and t - hit[0] < ALERTS_TTL_S:
                        return hit[1]
                req = nws.alerts_request(cell[0] * ALERTS_CELL_DEG, cell[1] * ALERTS_CELL_DEG)
                data = fetch(fetcher, req, optional=True)
                with alerts_lock:
                    alerts_cache[cell] = (t, data)
                    for k in [k for k, v in alerts_cache.items() if t - v[0] >= ALERTS_TTL_S]:
                        del alerts_cache[k]
                return data

            ctx = SpotContext(
                borders=load_borders(settings.config_dir / "borders.geojson"),
                locations=locs,
                peaks=read_peaks(settings.osm_path),
                conn=conn,
                spot_used=spot_used,
                alerts=alerts,
                tile_peaks=lambda a, b: peaks_near(get_tile, a, b),
            )
            times: dict[str, float] = {}
            t0 = time.monotonic()
            try:
                snap = build_spot(fetcher, cfg, ctx, lat, lon, now, times)
                log.info(
                    "spot %s built in %.1fs (%s)",
                    snap.location.id,
                    time.monotonic() - t0,
                    ", ".join(f"{k} {v:g}s" for k, v in sorted(times.items(), key=lambda x: -x[1])),
                )
                return snap
            except SpotUnavailable:
                log.warning(
                    "spot %.3f,%.3f failed after %.1fs (%s)",
                    lat,
                    lon,
                    time.monotonic() - t0,
                    ", ".join(f"{k} {v:g}s" for k, v in times.items()),
                )
                raise
            finally:
                if conn is not None:
                    try:
                        repo.record_usage(conn, fetcher, public_as=repo.SPOT_HOST)
                    except sqlite3.Error as e:
                        log.warning("spot usage not recorded: %s", e)
                    conn.close()

    return SpotService(cfg, build)
