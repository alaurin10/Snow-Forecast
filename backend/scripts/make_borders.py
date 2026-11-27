"""Make config/borders.geojson: the US and Canada outlines that decide whether a point
can have a forecast anywhere (snowwatch/spots.py) and which country's models it gets.

From Natural Earth's admin-0 countries at 1:50m (public domain), simplified a little
(Douglas-Peucker, ~0.005°, about 500 m) and rounded to 3 decimals (~100 m). Run once,
when Natural Earth changes:

    curl -sSLo ne50.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson
    uv run python scripts/make_borders.py ne50.geojson ../config/borders.geojson
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOLERANCE = 0.005  # degrees
DIGITS = 3
COUNTRIES = {"USA": "US", "CAN": "CA"}


def _dp(points: list[list[float]], tol: float) -> list[list[float]]:
    """Douglas-Peucker on an open line (iterative, so long coasts don't recurse deeply)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a][:2], points[b][:2]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5
        best, at = -1.0, -1
        for i in range(a + 1, b):
            x, y = points[i][:2]
            if norm == 0:
                d = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
            else:
                d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
            if d > best:
                best, at = d, i
        if best > tol:
            keep[at] = True
            stack += [(a, at), (at, b)]
    return [p for p, k in zip(points, keep, strict=True) if k]


def _ring(ring: list[list[float]]) -> list[list[float]] | None:
    """A closed ring, simplified and rounded; None if it collapses."""
    half = len(ring) // 2  # simplify as two halves so the ring keeps its shape
    pts = _dp(ring[: half + 1], TOLERANCE)[:-1] + _dp(ring[half:], TOLERANCE)
    out: list[list[float]] = []
    for x, y in ((round(p[0], DIGITS), round(p[1], DIGITS)) for p in pts):
        if not out or out[-1] != [x, y]:
            out.append([x, y])
    if out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else None


def main(src: Path, dst: Path) -> None:
    world = json.loads(src.read_text())
    features: list[dict[str, Any]] = []
    for f in world["features"]:
        code = COUNTRIES.get(f["properties"].get("ADM0_A3"))
        if code is None:
            continue
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out = []
        for poly in polys:
            rings = [r for r in (_ring(r) for r in poly) if r]
            if rings and len(rings[0]) >= 4:
                out.append(rings)
        features.append(
            {
                "type": "Feature",
                "properties": {"country": code},
                "geometry": {"type": "MultiPolygon", "coordinates": out},
            }
        )
    doc = {
        "type": "FeatureCollection",
        "source": "Natural Earth admin-0 countries 1:50m v5.1.2 (public domain), simplified",
        "features": sorted(features, key=lambda f: f["properties"]["country"], reverse=True),
    }
    dst.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    print(f"{dst}: {dst.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
