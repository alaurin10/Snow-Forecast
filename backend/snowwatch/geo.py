"""Small geometry helpers: distance and point-in-polygon on GeoJSON (lon, lat)."""

from __future__ import annotations

import itertools
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


def destination(lat: float, lon: float, bearing_deg: float, km: float) -> tuple[float, float]:
    """(lat, lon) `km` from a point along a bearing (degrees clockwise from north)."""
    p1, l1 = math.radians(lat), math.radians(lon)
    b, d = math.radians(bearing_deg), km / EARTH_KM
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2)
    )
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """The initial bearing from the first point to the second, 0–360 clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(bearing: float) -> str:
    """The 8-point compass direction of a bearing: N, NE, E …"""
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[round(bearing / 45) % 8]


def edge_km(geometry: dict[str, Any], lat: float, lon: float) -> float:
    """The distance from a point to the nearest edge of a (multi)polygon, roughly (flat
    projection about the point: fine for a few km)."""
    kx = math.cos(math.radians(lat)) * math.pi * EARTH_KM / 180
    ky = math.pi * EARTH_KM / 180
    best = math.inf
    for poly in polygons(geometry):
        for ring in poly:
            for (x1, y1), (x2, y2) in itertools.pairwise(ring):
                ax, ay = (x1 - lon) * kx, (y1 - lat) * ky
                bx, by = (x2 - lon) * kx, (y2 - lat) * ky
                dx, dy = bx - ax, by - ay
                n = dx * dx + dy * dy
                t = 0.0 if n == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / n))
                best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best
