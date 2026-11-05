"""Auto-detect the details of a new location from its pins (Manage page).

Given the base/mid/summit points (a resort's single point or a tour's trailhead
and high point), fill in: elevations from the terrain model, timezone, country,
NWS office and radar, the nearest SNOTEL stations, the avalanche zone and
default links. Everything returned is a suggestion the owner reviews.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field

from snowwatch.geo import contains, haversine_km
from snowwatch.http import Fetcher, FetchError
from snowwatch.models import AvyRef, Band, BandName
from snowwatch.sources import nws
from snowwatch.sources.base import Request, fetch
from snowwatch.sources.openmeteo import FORECAST_URL, SOURCE, elevation_request

SNOTEL_RADIUS_KM = 25.0
CANADA_RADIUS_KM = 40.0  # BC snow pillows are sparser than SNOTEL
MID_SHARE = 0.6  # mid = base + 60% of the vertical (the prototype's Crystal values)


class Pin(BaseModel):
    band: BandName
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    elev_m: float | None = None
    label: str | None = None


class ResolveIn(BaseModel):
    name: str = ""
    kind: Literal["resort", "backcountry"] = "resort"
    pins: list[Pin] = Field(min_length=1)
    catalog_id: str | None = None


class SnotelCandidate(BaseModel):
    triplet: str
    name: str
    distance_km: float
    elev_m: float | None


class ResolveOut(BaseModel):
    id: str
    name: str
    kind: str
    region: str
    country: Literal["US", "CA"]
    tz: str | None
    bands: list[Band]
    snotel: str | None
    snotel_candidates: list[SnotelCandidate]
    nws_office: str | None
    radar_station: str | None
    avy: AvyRef | None
    avy_name: str | None
    links: dict[str, str]
    warnings: list[str]


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (s or "location")[:40]


def _elevations(
    fetcher: Fetcher, points: list[tuple[float, float]], warnings: list[str]
) -> list[float | None]:
    try:
        data = fetch(fetcher, elevation_request(points))
        return [float(e) for e in data.get("elevation", [])]
    except (FetchError, TypeError, ValueError) as e:
        warnings.append(f"terrain elevation unavailable: {e}")
        return [None] * len(points)


def _timezone(fetcher: Fetcher, lat: float, lon: float, warnings: list[str]) -> str | None:
    req = Request(
        "tz",
        SOURCE,
        FORECAST_URL,
        {
            "latitude": f"{lat:g}",
            "longitude": f"{lon:g}",
            "hourly": "temperature_2m",
            "forecast_days": "1",
            "timezone": "auto",
        },
        1.0,
    )
    try:
        tz = fetch(fetcher, req).get("timezone")
        return str(tz) if tz else None
    except FetchError as e:
        warnings.append(f"timezone unavailable: {e}")
        return None


def resolve(conn: sqlite3.Connection, fetcher: Fetcher, req: ResolveIn) -> ResolveOut:
    warnings: list[str] = []
    pins = {p.band: p for p in req.pins}
    cat: dict[str, Any] | None = None
    if req.catalog_id:
        row = conn.execute(
            "SELECT * FROM catalog_ski_areas WHERE id = ?", (req.catalog_id,)
        ).fetchone()
        cat = dict(row) if row else None

    # Fill in the three bands. A resort usually has one point; elevations come
    # from the catalog's lift/run statistics, else the terrain model.
    anchor = pins.get("mid") or pins.get("summit") or pins.get("base") or req.pins[0]
    pts = {
        b: pins.get(b) or Pin(band=b, lat=anchor.lat, lon=anchor.lon)
        for b in ("base", "mid", "summit")
    }
    if cat:
        if pts["base"].elev_m is None and cat.get("min_elev_m") is not None:
            pts["base"].elev_m = float(cat["min_elev_m"])
        if pts["summit"].elev_m is None and cat.get("max_elev_m") is not None:
            pts["summit"].elev_m = float(cat["max_elev_m"])
    # Look up base and summit, plus mid when it is its own pin (a tour with
    # three pins). A resort's single pin only marks where it is, so its mid
    # elevation comes from the 60% rule below, not the terrain at that spot.
    separate_mid = "mid" in pins and len(pins) >= 2
    lookup = ["base", "summit"] + (["mid"] if separate_mid else [])
    missing = [b for b in lookup if pts[b].elev_m is None]
    if missing:
        found = _elevations(fetcher, [(pts[b].lat, pts[b].lon) for b in missing], warnings)
        for b, e in zip(missing, found, strict=False):
            pts[b].elev_m = e
    base_e, summit_e = pts["base"].elev_m, pts["summit"].elev_m
    if pts["mid"].elev_m is None and base_e is not None and summit_e is not None:
        pts["mid"].elev_m = round(base_e + MID_SHARE * (summit_e - base_e))
    elevs = [pts[b].elev_m for b in ("base", "mid", "summit")]
    if any(e is None for e in elevs):
        warnings.append("set the elevations by hand: the terrain model gave no value")
    elif not (elevs[0] < elevs[1] < elevs[2]):  # type: ignore[operator]
        warnings.append("elevations must rise from base to summit; adjust the pins or values")

    mid = pts["mid"]
    resort = req.kind == "resort"
    labels = {
        "base": "Base" if resort else "Trailhead",
        "mid": "Mid-mountain" if resort else "Mid",
        "summit": "Summit" if resort else "High point",
    }
    bands = [
        Band(
            band=b,
            label=pts[b].label or labels[b],
            lat=round(pts[b].lat, 5),
            lon=round(pts[b].lon, 5),
            elev_m=round(pts[b].elev_m or 0),
        )
        for b in ("base", "mid", "summit")
    ]

    # NWS answers only for the US, which also tells us the country.
    nws_office = radar = state = None
    country: Literal["US", "CA"] = "CA"
    try:
        props = fetch(fetcher, nws.points_request(mid.lat, mid.lon)).get("properties") or {}
        country = "US"
        nws_office, radar = props.get("cwa"), props.get("radarStation")
        rel = (props.get("relativeLocation") or {}).get("properties") or {}
        state = rel.get("state") if isinstance(rel.get("state"), str) else None
    except FetchError:
        pass
    if cat and cat.get("country") in ("US", "CA"):
        country = cat["country"]
    tz = _timezone(fetcher, mid.lat, mid.lon, warnings)

    # Nearest SNOTEL stations, closest in elevation first.
    candidates = rank_stations(conn, mid.lat, mid.lon, mid.elev_m or 0, country)
    if not has_stations(conn, country):
        warnings.append("snow station list is empty; run `snowwatch lookups refresh`")

    # Avalanche zone by point-in-polygon (bounding box first).
    avy = None
    avy_name = None
    avy_link = None
    provider = "nac" if country == "US" else "avcan"
    for r in conn.execute("SELECT * FROM avy_zones WHERE provider = ?", (provider,)):
        x0, y0, x1, y1 = json.loads(r["bbox_json"])
        if (
            x0 <= mid.lon <= x1
            and y0 <= mid.lat <= y1
            and contains(json.loads(r["geometry_json"]), mid.lat, mid.lon)
        ):
            avy = AvyRef(
                provider=provider,
                center_id=r["center_id"],
                zone_id=r["zone_id"] if provider == "nac" else None,
            )
            avy_name, avy_link = r["name"], r["link"]
            break
    if avy is None and provider == "avcan":
        avy = AvyRef(provider="avcan")

    name = req.name or (cat["name"] if cat else "")
    # A catalog region when there is one; otherwise the avalanche zone and state,
    # e.g. "Snoqualmie Pass, WA".
    region = (cat.get("region") or "") if cat else ""
    if not region:
        region = ", ".join(p for p in (avy_name, state) if p)
    links: dict[str, str] = {}
    if country == "US":
        links["NWS forecast"] = (
            f"https://forecast.weather.gov/MapClick.php?lat={mid.lat:.3f}&lon={mid.lon:.3f}"
        )
        if radar:
            links[f"Radar ({radar})"] = (
                f"https://radar.weather.gov/station/{radar.lower()}/standard"
            )
        if avy_link:
            center = avy.center_id if avy else "avalanche center"
            links[f"Avalanche ({center})"] = avy_link
    else:
        links["Mountain forecast (ECCC)"] = "https://weather.gc.ca/mountain_forecast/"
        links["Avalanche Canada"] = "https://avalanche.ca/map"
    if cat and cat.get("website"):
        links["Resort website"] = cat["website"]

    return ResolveOut(
        id=slugify(name),
        name=name,
        kind=req.kind,
        region=region,
        country=country,
        tz=tz,
        bands=bands,
        snotel=candidates[0].triplet if candidates else None,
        snotel_candidates=candidates,
        nws_office=nws_office,
        radar_station=radar,
        avy=avy,
        avy_name=avy_name,
        links=links,
        warnings=warnings,
    )


def _network(country: str) -> str:
    # SNOTEL in the US; BC River Forecast Centre snow pillows in Canada.
    return "%:SNTL" if country == "US" else "%:BC:ASWS"


def has_stations(conn: sqlite3.Connection, country: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM snotel_stations WHERE triplet LIKE ? LIMIT 1", (_network(country),)
        ).fetchone()
        is not None
    )


def rank_stations(
    conn: sqlite3.Connection, lat: float, lon: float, elev_m: float, country: str, limit: int = 3
) -> list[SnotelCandidate]:
    """The best nearby snow stations: near and at a similar height.

    Every 50 m of elevation difference counts like 1 km of distance (by
    elevation alone, a station across the crest can beat one beside the lifts).
    """
    radius = SNOTEL_RADIUS_KM if country == "US" else CANADA_RADIUS_KM
    out: list[SnotelCandidate] = []
    for r in conn.execute(
        "SELECT triplet, name, lat, lon, elev_m FROM snotel_stations WHERE triplet LIKE ?",
        (_network(country),),
    ):
        d = haversine_km(lat, lon, r["lat"], r["lon"])
        if d <= radius:
            out.append(
                SnotelCandidate(
                    triplet=r["triplet"],
                    name=r["name"],
                    distance_km=round(d, 1),
                    elev_m=r["elev_m"],
                )
            )
    out.sort(key=lambda c: c.distance_km + abs((c.elev_m or 0) - elev_m) / 50)
    return out[:limit]
