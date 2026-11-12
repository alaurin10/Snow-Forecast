"""Every snow station in the map's box, for the map's stations layer (docs/MAP-PLAN.md, B9).

The worker writes `data/stations/stations.json` every hour: each SNOTEL station and each
BC River Forecast Centre snow pillow in the box, with its snow depth now, the change over
the last 24 hours and a week of daily depths for a sparkline. SNOTEL comes from three
AWDB requests for the whole network (station list, hourly depth for the last three days,
daily depth for the last eight); the BC network from the same wide CSV the forecasts use.

A network that fails keeps its stations from the last file, so one outage doesn't empty
half the map. Depths are as the stations report them: pillows read a few cm high or low,
and a 24-hour change includes settling (it can be negative).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from snowwatch.http import Fetcher, FetchError
from snowwatch.sources import bc_asws
from snowwatch.sources.base import Request, fetch
from snowwatch.sources.snotel import BASE, IN_TO_CM, SOURCE, all_stations_request

log = logging.getLogger("snowwatch.stations")

Box = tuple[float, float, float, float]  # south, west, north, east
DAYS = 8  # daily depths kept: a week of change
STALE_H = 72  # a station with nothing newer than this is left off
BC_TZ = ZoneInfo("America/Vancouver")
SNOTEL_SITE = "https://wcc.sc.egov.usda.gov/nwcc/site?sitenum={id}"


class StationDay(BaseModel):
    date: str
    depth_cm: float | None


class MapStation(BaseModel):
    id: str
    name: str
    network: Literal["snotel", "bc"]
    lat: float
    lon: float
    elev_m: float | None
    obs_time: str | None  # UTC, ISO
    depth_cm: float | None
    change24_cm: float | None  # depth now minus 24 hours ago (settling makes it negative)
    daily: list[StationDay]  # oldest first, the station's own days
    url: str | None = None


class StationsOut(BaseModel):
    generated_at: str
    stations: list[MapStation]
    errors: list[str] = []


def _inside(box: Box, lat: float, lon: float) -> bool:
    s, w, n, e = box
    return s <= lat <= n and w <= lon <= e


def _cm(v: Any) -> float | None:
    """Inches to cm; a negative depth is a sensor fault, not a value."""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x < 0 else round(x * IN_TO_CM, 1)


def _depth_request(name: str, duration: str, begin: str, end: str) -> Request:
    """Snow depth for every SNOTEL station (about 900: under the API's limit of 1,000
    station elements a request)."""
    return Request(
        name,
        SOURCE,
        f"{BASE}/data",
        {
            "stationTriplets": "*:*:SNTL",
            "elements": "SNWD",
            "duration": duration,
            "beginDate": begin,
            "endDate": end,
        },
    )


def _values(blob: Any) -> dict[str, list[tuple[str, Any]]]:
    """{triplet: [(date, value), …]} from an AWDB data response."""
    out: dict[str, list[tuple[str, Any]]] = {}
    for st in blob if isinstance(blob, list) else []:
        trip = st.get("stationTriplet") if isinstance(st, dict) else None
        if not trip:
            continue
        vals: list[tuple[str, Any]] = []
        for d in st.get("data") or []:
            if (d.get("stationElement") or {}).get("elementCode") == "SNWD":
                vals = [(v["date"], v.get("value")) for v in d.get("values") or [] if "date" in v]
        out[trip] = vals
    return out


def _change(series: list[tuple[datetime, float]], hours: int) -> float | None:
    """Depth now minus `hours` ago, if there's a reading within 3 hours of that time."""
    if not series:
        return None
    last_t, last_v = series[-1]
    cut = last_t - timedelta(hours=hours)
    prior = [(t, v) for t, v in series if t <= cut]
    if not prior or cut - prior[-1][0] > timedelta(hours=3):
        return None
    return round(last_v - prior[-1][1], 1)


def snotel_stations(
    meta: Any, hourly: Any, daily: Any, box: Box, now: datetime
) -> list[MapStation]:
    """SNOTEL stations in the box with a reading in the last three days. Hourly times are
    the station's local standard time (`dataTimeZone` hours from UTC)."""
    hours = _values(hourly)
    days = _values(daily)
    out = []
    for s in meta if isinstance(meta, list) else []:
        if not isinstance(s, dict):
            continue
        trip, lat, lon = s.get("stationTriplet"), s.get("latitude"), s.get("longitude")
        if not trip or lat is None or lon is None or not _inside(box, lat, lon):
            continue
        offset = timedelta(hours=float(s.get("dataTimeZone") or -8))
        series: list[tuple[datetime, float]] = []
        for t, v in hours.get(trip, []):
            cm = _cm(v)
            if cm is None:
                continue
            try:
                local = datetime.strptime(t, "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            series.append(((local - offset).replace(tzinfo=UTC), cm))
        series.sort()
        if not series or now - series[-1][0] > timedelta(hours=STALE_H):
            continue
        daily_rows = [StationDay(date=d[:10], depth_cm=_cm(v)) for d, v in days.get(trip, [])]
        elev_ft = s.get("elevation")
        out.append(
            MapStation(
                id=trip,
                name=s.get("name") or trip,
                network="snotel",
                lat=round(float(lat), 5),
                lon=round(float(lon), 5),
                elev_m=None if elev_ft is None else round(float(elev_ft) * 0.3048),
                obs_time=series[-1][0].isoformat(timespec="minutes"),
                depth_cm=series[-1][1],
                change24_cm=_change(series, 24),
                daily=daily_rows[-DAYS:],
                url=SNOTEL_SITE.format(id=s.get("stationId") or trip.split(":")[0]),
            )
        )
    return out


def bc_stations(
    rows: Iterable[Mapping[str, Any]], depth: Mapping[str, bc_asws.Series], box: Box, now: datetime
) -> list[MapStation]:
    """BC snow pillows in the box. Daily depths are the reading at local midnight, like
    SNOTEL's daily values."""
    out = []
    today = now.astimezone(BC_TZ).date()
    for r in rows:
        sid = bc_asws.station_id(str(r["triplet"]))
        if not _inside(box, r["lat"], r["lon"]):
            continue
        series = [(datetime.fromisoformat(t), round(v, 1)) for t, v in depth.get(sid, []) if v >= 0]
        series.sort()
        if not series or now - series[-1][0] > timedelta(hours=STALE_H):
            continue
        daily = []
        for i in range(DAYS - 1, -1, -1):
            d: date = today - timedelta(days=i)
            midnight = datetime(d.year, d.month, d.day, tzinfo=BC_TZ)
            at = next(
                (v for t, v in series if midnight <= t <= midnight + timedelta(hours=3)), None
            )
            daily.append(StationDay(date=d.isoformat(), depth_cm=at))
        out.append(
            MapStation(
                id=str(r["triplet"]),
                name=str(r["name"]),
                network="bc",
                lat=round(float(r["lat"]), 5),
                lon=round(float(r["lon"]), 5),
                elev_m=None if r.get("elev_m") is None else round(float(r["elev_m"])),
                obs_time=series[-1][0].isoformat(timespec="minutes"),
                depth_cm=series[-1][1],
                change24_cm=_change(series, 24),
                daily=daily,
            )
        )
    return out


def read(path: Path) -> StationsOut | None:
    try:
        return StationsOut.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return None


def refresh(path: Path, fetcher: Fetcher, box: Box, now: datetime | None = None) -> StationsOut:
    """Fetch both networks and write the file (each keeps its old stations if it fails)."""
    now = now or datetime.now(UTC)
    old = read(path)
    errors: list[str] = []
    stations: list[MapStation] = []

    try:
        today = now.date()
        meta = fetch(fetcher, all_stations_request())
        hourly = fetch(
            fetcher,
            _depth_request(
                "snotel_depth_hourly",
                "HOURLY",
                f"{(today - timedelta(days=2)).isoformat()} 00:00",
                f"{today.isoformat()} 23:59",
            ),
        )
        daily = fetch(
            fetcher,
            _depth_request(
                "snotel_depth_daily",
                "DAILY",
                (today - timedelta(days=DAYS)).isoformat(),
                today.isoformat(),
            ),
        )
        stations += snotel_stations(meta, hourly, daily, box, now)
    except (FetchError, ValueError, KeyError, TypeError) as e:
        errors.append(f"snotel: {e}")
        stations += [s for s in (old.stations if old else []) if s.network == "snotel"]

    try:
        wfs = fetch(fetcher, bc_asws.stations_request())
        rows = bc_asws.station_rows(wfs)
        text = fetcher.get_text(bc_asws.csv_request("SD").url, source=bc_asws.SOURCE)
        depth = bc_asws.parse_wide_csv(text, {bc_asws.station_id(r["triplet"]) for r in rows})
        stations += bc_stations(rows, depth, box, now)
    except (FetchError, ValueError, KeyError, TypeError) as e:
        errors.append(f"bc-asws: {e}")
        stations += [s for s in (old.stations if old else []) if s.network == "bc"]

    out = StationsOut(
        generated_at=now.isoformat(timespec="seconds"), stations=stations, errors=errors
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(out.model_dump_json())
    tmp.replace(path)
    return out
