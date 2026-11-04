"""National Weather Service API (US only). NWS asks for a User-Agent with contact details."""

from __future__ import annotations

from snowwatch.sources.base import Request

BASE = "https://api.weather.gov"
SOURCE = "nws"


def points_request(lat: float, lon: float) -> Request:
    return Request("nws_points", SOURCE, f"{BASE}/points/{lat:.4f},{lon:.4f}")


def alerts_request(lat: float, lon: float) -> Request:
    return Request("nws_alerts", SOURCE, f"{BASE}/alerts/active", {"point": f"{lat:.4f},{lon:.4f}"})
