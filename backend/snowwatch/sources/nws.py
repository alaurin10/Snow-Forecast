"""National Weather Service API (US only). NWS asks for a User-Agent with contact details."""

from __future__ import annotations

from typing import Any

from snowwatch.doc import Alert
from snowwatch.sources.base import Request

BASE = "https://api.weather.gov"
SOURCE = "nws"


def points_request(lat: float, lon: float) -> Request:
    return Request("nws_points", SOURCE, f"{BASE}/points/{lat:.4f},{lon:.4f}")


def alerts_request(lat: float, lon: float) -> Request:
    return Request("nws_alerts", SOURCE, f"{BASE}/alerts/active", {"point": f"{lat:.4f},{lon:.4f}"})


def parse_alerts(data: dict[str, Any]) -> list[Alert]:
    """Active alerts from `/alerts/active?point=` (ported from `pull_alerts`)."""
    out = []
    for f in data.get("features") or []:
        p = f.get("properties") or {}
        out.append(
            Alert(
                event=p.get("event"),
                headline=p.get("headline"),
                severity=p.get("severity"),
                onset=p.get("onset"),
                ends=p.get("ends") or p.get("expires"),
                url=p.get("@id") or f.get("id"),
            )
        )
    return out
