"""NRCS SNOTEL via the AWDB REST API. Values arrive in inches and °F."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from snowwatch.doc import Snotel, SnotelDay
from snowwatch.sources.base import Request

BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
SOURCE = "snotel"


def stations_request(state: str) -> Request:
    return Request(
        f"snotel_stations_{state}",
        SOURCE,
        f"{BASE}/stations",
        {
            "stationTriplets": f"*:{state}:SNTL",
            "returnForecastPointMetadata": "false",
            "returnReservoirMetadata": "false",
            "returnStationElements": "false",
        },
    )


def daily_request(triplet: str, begin: date, end: date) -> Request:
    return Request(
        "snotel_daily",
        SOURCE,
        f"{BASE}/data",
        {
            "stationTriplets": triplet,
            "elements": "SNWD,WTEQ,TOBS,PREC",
            "duration": "DAILY",
            "beginDate": begin.isoformat(),
            "endDate": end.isoformat(),
        },
    )


def hourly_request(triplet: str, begin: date, end: date) -> Request:
    return Request(
        "snotel_hourly",
        SOURCE,
        f"{BASE}/data",
        {
            "stationTriplets": triplet,
            "elements": "SNWD,TOBS",
            "duration": "HOURLY",
            "beginDate": f"{begin.isoformat()} 00:00",
            "endDate": f"{end.isoformat()} 23:59",
        },
    )


IN_TO_CM = 2.54
IN_TO_MM = 25.4
FT_TO_M = 0.3048


def _f_to_c(f: float | None) -> float | None:
    return None if f is None else (f - 32) * 5 / 9


def _series(blob: list[dict[str, Any]], element: str) -> list[tuple[str, float | None]]:
    for station in blob or []:
        for d in station.get("data", []):
            if d.get("stationElement", {}).get("elementCode") == element:
                return [(v["date"], v.get("value")) for v in d.get("values", [])]
    return []


def _scale(v: float | None, k: float) -> float | None:
    return None if v is None else v * k


def parse_snotel(
    triplet: str,
    daily: list[dict[str, Any]],
    hourly: list[dict[str, Any]],
    station: Mapping[str, Any] | None = None,
) -> Snotel:
    """Observed depth and SWE (ported from `pull_snotel`), converted to metric."""
    depth = dict(_series(daily, "SNWD"))
    swe = dict(_series(daily, "WTEQ"))
    tobs = dict(_series(daily, "TOBS"))
    prec = dict(_series(daily, "PREC"))
    dates = sorted(set(depth) | set(swe))
    rows = [
        SnotelDay(
            date=d[:10],
            depth_cm=_scale(depth.get(d), IN_TO_CM),
            swe_mm=_scale(swe.get(d), IN_TO_MM),
            temp_c=_f_to_c(tobs.get(d)),
            precip_mm=_scale(prec.get(d), IN_TO_MM),
        )
        for d in dates
    ]
    hv = [(t, v) for t, v in _series(hourly, "SNWD") if v is not None]

    def change(hours: int) -> float | None:
        if not hv:
            return None
        last = datetime.fromisoformat(hv[-1][0])
        prior = [v for t, v in hv if datetime.fromisoformat(t) <= last - timedelta(hours=hours)]
        return None if not prior else (hv[-1][1] - prior[-1]) * IN_TO_CM

    depth_now = (
        hv[-1][1] * IN_TO_CM
        if hv
        else next((r.depth_cm for r in reversed(rows) if r.depth_cm is not None), None)
    )
    meta: Mapping[str, Any] = station or {}
    elev_ft = meta.get("elevation")
    return Snotel(
        triplet=triplet,
        name=meta.get("name"),
        elev_m=None if elev_ft is None else float(elev_ft) * FT_TO_M,
        obs_time=hv[-1][0] if hv else None,
        depth_cm=depth_now,
        swe_mm=next((r.swe_mm for r in reversed(rows) if r.swe_mm is not None), None),
        change24_cm=change(24),
        change72_cm=change(72),
        daily=rows,
    )


def all_stations_request() -> Request:
    """Every SNOTEL station in every state (about 900), with location and elevation."""
    return Request(
        "snotel_stations_all",
        SOURCE,
        f"{BASE}/stations",
        {
            "stationTriplets": "*:*:SNTL",
            "returnForecastPointMetadata": "false",
            "returnReservoirMetadata": "false",
            "returnStationElements": "false",
        },
    )
