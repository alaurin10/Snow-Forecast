"""Small geometry helpers: distance and point-in-polygon on GeoJSON (lon, lat)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

EARTH_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def _in_ring(lon: float, lat: float, ring: Sequence[Sequence[float]]) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def polygons(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    if geometry.get("type") == "Polygon":
        return [geometry["coordinates"]]
    if geometry.get("type") == "MultiPolygon":
        return list(geometry["coordinates"])
    return []


def contains(geometry: dict[str, Any], lat: float, lon: float) -> bool:
    """True if the point is inside the (multi)polygon, honouring holes."""
    for poly in polygons(geometry):
        if (
            poly
            and _in_ring(lon, lat, poly[0])
            and not any(_in_ring(lon, lat, h) for h in poly[1:])
        ):
            return True
    return False


def bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """(min lon, min lat, max lon, max lat)."""
    pts = [p for poly in polygons(geometry) for ring in poly for p in ring]
    if geometry.get("type") == "Point":
        pts = [geometry["coordinates"]]
    if not pts:
        return None
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return min(lons), min(lats), max(lons), max(lats)


def centroid(geometry: dict[str, Any]) -> tuple[float, float] | None:
    """(lat, lon): the point itself, or the mean of a polygon's outer-ring vertices."""
    if geometry.get("type") == "Point":
        lon, lat = geometry["coordinates"][:2]
        return lat, lon
    rings = [poly[0] for poly in polygons(geometry) if poly]
    pts = [p for ring in rings for p in ring[:-1] or ring]
    if not pts:
        return None
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)
