"""Names of rivers, creeks and lakes around the locations, from OpenStreetMap, for the
labels over satellite imagery (docs/MAP-PLAN.md, "Labels over imagery").

The map's other labels come from OpenFreeMap's vector tiles of OpenStreetMap, and those
fall short of Esri's label pictures (which they replaced) in two ways near the
mountains: a river or creek is cut into pieces too short to write its name along at
zooms 11-12, and a lake like Keechelus is only named from zoom 13. So the worker asks
Overpass weekly, in the same box round each location as the ski map (`osm.boxes`), for:

- named rivers and streams, each joined into whole lines by name and simplified, so a
  name can be written along a long stretch at any zoom;
- named lakes and reservoirs, as one name point inside each (the middle of its widest
  east-west crossing) with its area, so bigger lakes can be named sooner.

The file also lists the boxes, so the map can leave out the tiles' own river and lake
names inside them (two names for one lake otherwise).
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import time
from collections import defaultdict
from collections.abc import Iterable
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx

from snowwatch import osm

log = logging.getLogger("snowwatch.osm")

# Bumped when what's asked for or how it's drawn up changes, so the file is made again.
VERSION = 1
# Label lines needn't follow every bend: ~15 m is plenty, and keeps the file small.
SIMPLIFY_DEG = 0.00015
# A stretch shorter than this has no room for its name at the zooms that matter.
MIN_LINE_M = 300.0

Coord = list[float]


def queries(box: tuple[float, float, float, float]) -> list[str]:
    """Two small queries per box (one big one times out on the public servers)."""
    s, w, n, e = box
    b = f"({s},{w},{n},{e})"
    return [
        f'[out:json][timeout:90];way["waterway"~"^(river|stream)$"]["name"]{b};out tags geom;',
        f'[out:json][timeout:90];(way["natural"="water"]["name"]{b};'
        f'relation["natural"="water"]["name"]{b};);'
        # A relation brings its members' shapes only with the body ("out geom").
        "out geom;",
    ]


def _metres(a: Coord, b: Coord) -> float:
    k = math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((b[0] - a[0]) * k, b[1] - a[1]) * 111_320


def length_m(line: list[Coord]) -> float:
    return sum(_metres(line[i], line[i + 1]) for i in range(len(line) - 1))


def join(pieces: list[list[Coord]]) -> list[list[Coord]]:
    """Lines that share ends joined into as few as they make (a river is mapped as many
    ways); each piece may be turned round to fit."""

    def end(p: Coord) -> tuple[float, float]:
        return (p[0], p[1])

    lines = [list(p) for p in pieces if len(p) >= 2]
    merged = True
    while merged:
        merged = False
        ends: dict[tuple[float, float], list[int]] = defaultdict(list)
        for i, ln in enumerate(lines):
            ends[end(ln[0])].append(i)
            ends[end(ln[-1])].append(i)
        used: set[int] = set()
        out: list[list[Coord]] = []
        for i, ln in enumerate(lines):
            if i in used:
                continue
            used.add(i)
            cur = ln
            grew = True
            while grew:
                grew = False
                for at_end in (True, False):
                    key = end(cur[-1] if at_end else cur[0])
                    j = next((j for j in ends.get(key, []) if j not in used), None)
                    if j is None:
                        continue
                    other = lines[j]
                    if at_end:
                        cur = cur + (other[1:] if end(other[0]) == key else other[::-1][1:])
                    else:
                        cur = (other[:-1] if end(other[-1]) == key else other[::-1][:-1]) + cur
                    used.add(j)
                    merged = grew = True
                    break
            out.append(cur)
        lines = out
    return lines


def ring_area_km2(ring: list[Coord]) -> float:
    """A ring's area (shoelace, in local metres)."""
    if len(ring) < 4:
        return 0.0
    lat0 = sum(p[1] for p in ring) / len(ring)
    k = math.cos(math.radians(lat0)) * 111_320
    pts = [(p[0] * k, p[1] * 111_320) for p in ring]
    a = sum(pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1] for i in range(len(pts) - 1))
    return abs(a) / 2 / 1e6


def label_point(ring: list[Coord]) -> Coord:
    """A point inside a ring for its name: the middle of its widest east-west crossing
    near the middle (a long, bent reservoir's centroid can be on shore)."""
    lats = [p[1] for p in ring]
    lo, hi = min(lats), max(lats)
    best: tuple[float, Coord] | None = None
    for f in (0.5, 0.4, 0.6, 0.3, 0.7):
        y = lo + (hi - lo) * f
        xs = sorted(
            a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            for a, b in pairwise(ring)
            if (a[1] > y) != (b[1] > y)
        )
        for x0, x1 in zip(xs[::2], xs[1::2], strict=False):
            if best is None or x1 - x0 > best[0]:
                best = (x1 - x0, [round((x0 + x1) / 2, 6), round(y, 6)])
    if best is None:
        return [round(sum(p[0] for p in ring) / len(ring), 6), round((lo + hi) / 2, 6)]
    return best[1]


def _lake(el: dict[str, Any]) -> tuple[list[Coord], float] | None:
    """A lake's biggest outer ring and its whole area (outer rings less holes)."""
    if el.get("type") == "way":
        ring = osm._coords(el.get("geometry"))
        if len(ring) < 4 or ring[0] != ring[-1]:
            return None
        return ring, ring_area_km2(ring)
    members = el.get("members") or []
    outer = osm.rings([osm._coords(m.get("geometry")) for m in members if m.get("role") == "outer"])
    inner = osm.rings([osm._coords(m.get("geometry")) for m in members if m.get("role") == "inner"])
    outer = [r for r in outer if len(r) >= 4]
    if not outer:
        return None
    area = sum(ring_area_km2(osm._closed(r)) for r in outer) - sum(
        ring_area_km2(osm._closed(r)) for r in inner
    )
    biggest = max(outer, key=lambda r: ring_area_km2(osm._closed(r)))
    return osm._closed(biggest), max(area, 0.0)


def to_geojson(
    elements: list[dict[str, Any]], bxs: list[tuple[float, float, float, float]]
) -> dict[str, Any]:
    feats: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    streams: dict[tuple[str, str], list[list[Coord]]] = defaultdict(list)
    lakes: dict[str, tuple[float, Coord]] = {}
    for el in elements:
        key = (str(el.get("type")), int(el.get("id", 0)))
        if key in seen:
            continue
        seen.add(key)
        tags = el.get("tags") or {}
        name = str(tags.get("name") or "").strip()
        if not name:
            continue
        if tags.get("waterway") in ("river", "stream") and el.get("type") == "way":
            streams[(name, tags["waterway"])].append(osm._coords(el.get("geometry")))
        elif tags.get("natural") == "water":
            got = _lake(el)
            if got is None:
                continue
            ring, area = got
            # One name per lake: a lake mapped twice, or in parts, keeps its biggest.
            if name not in lakes or area > lakes[name][0]:
                lakes[name] = (area, label_point(ring))
    for (name, cls), pieces in sorted(streams.items()):
        for line in join(pieces):
            if length_m(line) < MIN_LINE_M:
                continue
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": osm.simplify(line, SIMPLIFY_DEG),
                    },
                    "properties": {"kind": "water", "class": cls, "name": name},
                }
            )
    for name, (area, pt) in sorted(lakes.items()):
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": pt},
                "properties": {"kind": "lake", "name": name, "area": round(area, 3)},
            }
        )
    # Where these names replace the tiles' own (west, south, east, north).
    return {
        "type": "FeatureCollection",
        "boxes": [[w, s, e, n] for s, w, n, e in bxs],
        "features": feats,
    }


def _part_path(path: Path, box: tuple[float, float, float, float]) -> Path:
    return path.parent / f"{path.stem}-boxes" / ("_".join(f"{v:.3f}" for v in box) + ".json.gz")


def _read_part(part: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(gzip.decompress(part.read_bytes()))
    except (OSError, ValueError, EOFError):
        return None
    if not isinstance(data, dict) or data.get("v") != VERSION:
        return None
    return data


def refresh(
    path: Path,
    points: Iterable[tuple[float, float]],
    client: httpx.Client,
    *,
    now: float | None = None,
    force: bool = False,
    pause: float = 1.0,
) -> bool:
    """Fetch each location's box again if it's a week old (six hours if it had nothing)
    or new, and rewrite the file if any changed. A box Overpass fails for keeps what it
    had (and is tried again next time); one never fetched is left out of the file and
    its `boxes`, so the tiles name things there. Returns whether it wrote the file.

    Each box's answer is kept as it came (`<file>-boxes/`, gzipped), and the file is made
    from all of them together, so a river or lake in two boxes is named once."""
    bxs = osm.boxes(points)
    now = now or time.time()
    changed = not path.exists()
    have: list[tuple[tuple[float, float, float, float], list[Any]]] = []
    first = True
    for box in bxs:
        part = _part_path(path, box)
        old = _read_part(part)
        if old is not None and not force:
            max_age = osm.MAX_AGE_S if old.get("elements") else osm.EMPTY_MAX_AGE_S
            if now - float(old.get("at", 0)) < max_age:
                have.append((box, old["elements"]))
                continue
        elements: list[Any] = []
        failed = False
        for q in queries(box):
            if not first and pause:
                time.sleep(pause)
            first = False
            got = osm.fetch_query(client, q)
            if got is None:
                failed = True
                break
            elements.extend(got)
        if failed:
            log.warning("map label data: no server answered for %s; keeping what it had", box)
            if old is not None:
                have.append((box, old["elements"]))
            continue
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(
            gzip.compress(json.dumps({"v": VERSION, "at": now, "elements": elements}).encode(), 6)
        )
        have.append((box, elements))
        changed = True
    # Boxes of locations no longer listed go.
    keep = {_part_path(path, b) for b in bxs}
    parts = path.parent / f"{path.stem}-boxes"
    if parts.exists():
        for f in parts.iterdir():
            if f not in keep:
                f.unlink(missing_ok=True)
                changed = True
    if not changed:
        return False
    fc = to_geojson([el for _, els in have for el in els], [b for b, _ in have])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(fc, separators=(",", ":")))
    tmp.replace(path)
    log.info(
        "map label data: %d rivers, creeks and lakes in %d of %d boxes",
        len(fc["features"]),
        len(have),
        len(bxs),
    )
    return True
