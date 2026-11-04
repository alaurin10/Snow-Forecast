"""NRCS SNOTEL via the AWDB REST API. Values arrive in inches and °F."""

from __future__ import annotations

from datetime import date

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
