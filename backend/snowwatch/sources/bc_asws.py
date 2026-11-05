"""BC River Forecast Centre automated snow weather stations (snow pillows).

Each element is one wide CSV of hourly values for every station since the start
of the water year: a `DATE(UTC)` column, then one column per station named
"<id> <name>" (e.g. "3A20P Callaghan Creek"). Units: SD snow depth cm, SW snow
water mm, TA air temperature °C. Station locations come from the BC open-data
WFS layer. Licence: Open Government Licence – British Columbia.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from snowwatch.doc import Snotel, SnotelDay
from snowwatch.sources.base import Request

DATA = "https://www.env.gov.bc.ca/wsd/data_searches/snow/asws/data"
WFS = "https://openmaps.gov.bc.ca/geo/pub/wfs"
SOURCE = "bc-asws"
NETWORK = "BC River Forecast Centre"
ELEMENTS = ("SD", "SW", "TA")  # depth cm, snow water mm, air temperature °C
SUFFIX = ":BC:ASWS"


def csv_request(element: str) -> Request:
    return Request(f"bc_asws_{element}", SOURCE, f"{DATA}/{element}.csv")


def stations_request() -> Request:
    return Request(
        "bc_asws_stations",
        SOURCE,
        WFS,
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": "pub:WHSE_WATER_MANAGEMENT.SSL_SNOW_ASWS_STNS_SP",
            "outputFormat": "json",
            "srsName": "EPSG:4326",
        },
    )


def station_id(triplet: str) -> str:
    """'3A20P:BC:ASWS' → '3A20P'."""
    return triplet.split(":")[0]


def is_bc(triplet: str | None) -> bool:
    return bool(triplet) and str(triplet).endswith(SUFFIX)


def station_rows(wfs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Active stations as rows for the `snotel_stations` table."""
    out = []
    for f in wfs.get("features") or []:
        p = f.get("properties") or {}
        if p.get("STATUS") != "Active" or p.get("LATITUDE") is None:
            continue
        out.append(
            {
                "triplet": f"{p['LOCATION_ID']}{SUFFIX}",
                "name": p.get("LOCATION_NAME") or p["LOCATION_ID"],
                "state": "BC",
                "lat": float(p["LATITUDE"]),
                "lon": float(p["LONGITUDE"]),
                "elev_m": None if p.get("ELEVATION") is None else float(p["ELEVATION"]),
            }
        )
    return out


Series = list[tuple[str, float]]  # (UTC ISO hour, value)


def parse_wide_csv(text: str, keep: Iterable[str] | None = None) -> dict[str, Series]:
    """{station id: [(UTC time, value), …]} for the stations in `keep` (or all)."""
    wanted = set(keep) if keep is not None else None
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return {}
    cols = {i: name.split(" ", 1)[0] for i, name in enumerate(header) if i > 0}
    if wanted is not None:
        cols = {i: sid for i, sid in cols.items() if sid in wanted}
    out: dict[str, Series] = {sid: [] for sid in cols.values()}
    for row in reader:
        if not row:
            continue
        try:
            t = datetime.strptime(row[0], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        except ValueError:
            continue
        stamp = t.isoformat(timespec="minutes")
        for i, sid in cols.items():
            if i < len(row) and row[i].strip():
                try:
                    out[sid].append((stamp, float(row[i])))
                except ValueError:
                    continue
    return out


def station_slice(
    data: Mapping[str, Mapping[str, Series]], sid: str, since: datetime
) -> dict[str, Any]:
    """One station's recent hourly values, as stored in the raw cache: {"station", element: […]}."""
    cut = since.astimezone(UTC).isoformat(timespec="minutes")
    out: dict[str, Any] = {"station": sid}
    for el in ELEMENTS:
        out[el] = [[t, v] for t, v in data.get(el, {}).get(sid, []) if t >= cut]
    return out


def _at_or_after(series: Series, t: datetime, within_h: int = 3) -> float | None:
    """The first value at or after `t`, within a few hours."""
    lo = t.astimezone(UTC).isoformat(timespec="minutes")
    hi = (t + timedelta(hours=within_h)).astimezone(UTC).isoformat(timespec="minutes")
    for ts, v in series:
        if lo <= ts <= hi:
            return v
    return None


def parse_station(
    triplet: str, data: Mapping[str, Any], meta: Mapping[str, Any] | None, tz: str
) -> Snotel:
    """Daily start-of-day readings (matching SNOTEL's daily values) plus the latest values."""
    zone = ZoneInfo(tz)
    series: dict[str, Series] = {
        el: [(str(t), float(v)) for t, v in data.get(el) or [] if v is not None] for el in ELEMENTS
    }
    sd, sw, ta = series["SD"], series["SW"], series["TA"]
    stamps = [t for el in ELEMENTS for t, _ in series[el]]
    rows: list[SnotelDay] = []
    if stamps:
        first = datetime.fromisoformat(min(stamps)).astimezone(zone).date()
        last = datetime.fromisoformat(max(stamps)).astimezone(zone).date()
        d: date = first
        while d <= last:
            midnight = datetime(d.year, d.month, d.day, tzinfo=zone)
            temps = [
                v
                for t, v in ta
                if midnight <= datetime.fromisoformat(t) < midnight + timedelta(days=1)
            ]
            rows.append(
                SnotelDay(
                    date=d.isoformat(),
                    depth_cm=_at_or_after(sd, midnight),
                    swe_mm=_at_or_after(sw, midnight),
                    temp_c=round(sum(temps) / len(temps), 1) if temps else None,
                    precip_mm=None,
                )
            )
            d += timedelta(days=1)

    def change(hours: int) -> float | None:
        if not sd:
            return None
        last_t = datetime.fromisoformat(sd[-1][0])
        prior = [v for t, v in sd if datetime.fromisoformat(t) <= last_t - timedelta(hours=hours)]
        return None if not prior else sd[-1][1] - prior[-1]

    m: Mapping[str, Any] = meta or {}
    elev_ft = m.get("elevation")
    return Snotel(
        triplet=triplet,
        name=m.get("name") or station_id(triplet),
        elev_m=None if elev_ft is None else round(float(elev_ft) * 0.3048),
        obs_time=sd[-1][0] if sd else (sw[-1][0] if sw else None),
        depth_cm=sd[-1][1] if sd else None,
        swe_mm=sw[-1][1] if sw else None,
        change24_cm=change(24),
        change72_cm=change(72),
        daily=rows[-45:],
        network=NETWORK,
    )
