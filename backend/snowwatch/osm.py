"""Ski runs, lifts, peaks and mountain features around the locations, from OpenStreetMap,
for the Map page.

The worker asks Overpass once a week (or when the locations change) for the runs
(`piste:type`), lifts (`aerialway`), named peaks, huts and shelters, trailheads, passes,
cliffs, glaciers and ski-route relations (`route=ski|piste`, so a tour made of many ways
gets its name) in a box around each location, and saves them as one GeoJSON file. The
map draws them as vectors, with names that follow the lines and stay upright in 3D,
which picture tiles can't do.

Coverage is whatever OSM mappers have added: resorts are usually complete; ski-touring
and backcountry lines (`piste:type=skitour`) are hit and miss.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("snowwatch.osm")

# Public Overpass servers with worldwide data, tried in turn.
OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
MAX_AGE_S = 7 * 86400
# A file with nothing in it is tried again sooner.
EMPTY_MAX_AGE_S = 6 * 3600
# Around each location: ~35 x 35 km, enough for the resort and the touring nearby.
PAD_LAT = 0.16
PAD_LON = 0.24
RUN_TYPES = {"downhill", "skitour", "backcountry", "nordic", "sled", "hike", "snow_park"}
# Bumped when the query asks for more, so files from before are fetched again.
QUERY_VERSION = 2
# Shelters worth showing in the mountains (not picnic or bus shelters), unless named.
SHELTERS = {"basic_hut", "lean_to", "rock_shelter", "weather_shelter", "emergency"}
# Glaciers and cliffs are drawn as shapes; detail below ~8 m only adds bytes.
SIMPLIFY_DEG = 0.00008


def boxes(points: Iterable[tuple[float, float]]) -> list[tuple[float, float, float, float]]:
    """(south, west, north, east) around each point, rounded so the key is stable."""
    out = {
        (
            round(lat - PAD_LAT, 3),
            round(lon - PAD_LON, 3),
            round(lat + PAD_LAT, 3),
            round(lon + PAD_LON, 3),
        )
        for lat, lon in points
    }
    return sorted(out)


def query(bxs: list[tuple[float, float, float, float]]) -> str:
    """Lines and points with their tags and shape; then glaciers and ski routes in full
    (a relation only carries its members' shapes with the body)."""
    parts = []
    full = []
    for s, w, n, e in bxs:
        b = f"({s},{w},{n},{e})"
        parts.append(
            f'way["piste:type"]{b};way["aerialway"]{b};node["natural"="peak"]["name"]{b};'
            f'nw["tourism"~"^(alpine_hut|wilderness_hut)$"]{b};nw["amenity"="shelter"]{b};'
            f'node["highway"="trailhead"]{b};node["mountain_pass"="yes"]{b};'
            f'node["natural"="saddle"]["name"]{b};way["natural"="cliff"]{b};'
        )
        full.append(
            f'way["natural"="glacier"]{b};relation["natural"="glacier"]{b};'
            f'relation["route"~"^(ski|piste)$"]{b};'
        )
    return f"[out:json][timeout:120];({''.join(parts)});out tags geom;({''.join(full)});out geom;"


Coord = list[float]


def _ele(tags: dict[str, Any]) -> int | None:
    try:
        return round(float(str(tags.get("ele", "")).split()[0].replace(",", "")))
    except (ValueError, IndexError):
        return None


def _coords(geometry: list[dict[str, Any]] | None) -> list[Coord]:
    return [
        [round(p["lon"], 6), round(p["lat"], 6)]
        for p in geometry or []
        if isinstance(p, dict) and "lat" in p and "lon" in p
    ]


def simplify(line: list[Coord], tol: float = SIMPLIFY_DEG) -> list[Coord]:
    """Douglas-Peucker in degrees (longitude scaled by latitude), keeping the ends."""
    if len(line) < 3:
        return line
    k = math.cos(math.radians(line[0][1]))
    keep = [False] * len(line)
    keep[0] = keep[-1] = True
    stack = [(0, len(line) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = line[a][0] * k, line[a][1]
        bx, by = line[b][0] * k, line[b][1]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        worst, at = -1.0, -1
        for i in range(a + 1, b):
            px, py = line[i][0] * k, line[i][1]
            if norm == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dy * (px - ax) - dx * (py - ay)) / norm
            if d > worst:
                worst, at = d, i
        if at >= 0 and worst > tol:
            keep[at] = True
            stack.extend(((a, at), (at, b)))
    return [p for p, k_ in zip(line, keep, strict=True) if k_]


def rings(ways: list[list[Coord]]) -> list[list[Coord]]:
    """Closed rings joined end to end from a multipolygon's member ways. Pieces that
    never close (members cut off by the query) are dropped."""
    pool = [w[:] for w in ways if len(w) >= 2]
    out: list[list[Coord]] = []
    while pool:
        cur = pool.pop(0)
        while cur[0] != cur[-1]:
            for i, w in enumerate(pool):
                if w[0] == cur[-1]:
                    cur.extend(w[1:])
                elif w[-1] == cur[-1]:
                    cur.extend(w[-2::-1])
                elif w[-1] == cur[0]:
                    cur[:0] = w[:-1]
                elif w[0] == cur[0]:
                    cur[:0] = w[:0:-1]
                else:
                    continue
                pool.pop(i)
                break
            else:
                break
        if cur[0] == cur[-1] and len(cur) >= 4:
            out.append(cur)
    return out


def _inside(pt: Coord, ring: list[Coord]) -> bool:
    x, y = pt
    hit = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def _closed(ring: list[Coord]) -> list[Coord]:
    """Simplified, but still a closed ring of at least four points."""
    s = simplify(ring)
    return s if len(s) >= 4 else ring


def polygons(outer: list[list[Coord]], inner: list[list[Coord]]) -> list[list[list[Coord]]]:
    """GeoJSON polygons: each outer ring with the inner rings that lie in it."""
    polys = [[_closed(r)] for r in outer]
    for r in inner:
        for poly, o in zip(polys, outer, strict=True):
            if _inside(r[0], o):
                poly.append(_closed(r))
                break
    return polys


def _point(el: dict[str, Any]) -> Coord | None:
    """A node's position, or the middle of a way (a hut drawn as a building)."""
    if el.get("type") == "node" and "lat" in el:
        return [round(el["lon"], 6), round(el["lat"], 6)]
    pts = _coords(el.get("geometry"))
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return None
    return [
        round(sum(p[0] for p in pts) / len(pts), 6),
        round(sum(p[1] for p in pts) / len(pts), 6),
    ]


def _osm_id(el: dict[str, Any]) -> str:
    """The element's OpenStreetMap id as "n123", "w123" or "r123", for a link to it."""
    return f"{str(el.get('type', 'node'))[:1]}{el.get('id', 0)}"


def _place(el: dict[str, Any], tags: dict[str, Any]) -> dict[str, Any] | None:
    """Huts, shelters, trailheads and passes, as points."""
    tourism = tags.get("tourism")
    if tourism in ("alpine_hut", "wilderness_hut"):
        kind, typ = "hut", tourism
    elif tags.get("amenity") == "shelter":
        st = tags.get("shelter_type", "")
        if st not in SHELTERS and not tags.get("name"):
            return None
        if st in ("picnic_shelter", "public_transport", "field_shelter"):
            return None
        kind, typ = "hut", "shelter"
    elif tags.get("highway") == "trailhead":
        kind, typ = "trailhead", "trailhead"
    elif tags.get("mountain_pass") == "yes" or tags.get("natural") == "saddle":
        kind, typ = "pass", tags.get("natural") or "pass"
    else:
        return None
    at = _point(el)
    if at is None:
        return None
    props: dict[str, Any] = {
        "kind": kind,
        "type": typ,
        "name": tags.get("name", ""),
        "osm": _osm_id(el),
    }
    if (ele := _ele(tags)) is not None:
        props["ele"] = ele
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": at},
        "properties": props,
    }


def _relation(el: dict[str, Any], tags: dict[str, Any]) -> dict[str, Any] | None:
    """A glacier multipolygon or a ski route made of many ways."""
    members = [m for m in el.get("members") or [] if m.get("type") == "way"]
    if tags.get("natural") == "glacier":
        outer = rings([_coords(m.get("geometry")) for m in members if m.get("role") != "inner"])
        inner = rings([_coords(m.get("geometry")) for m in members if m.get("role") == "inner"])
        if not outer:
            return None
        return {
            "type": "Feature",
            "geometry": {"type": "MultiPolygon", "coordinates": polygons(outer, inner)},
            "properties": {"kind": "glacier", "name": tags.get("name", ""), "osm": _osm_id(el)},
        }
    if tags.get("route") in ("ski", "piste"):
        lines = [simplify(c) for m in members if len(c := _coords(m.get("geometry"))) >= 2]
        if not lines:
            return None
        return {
            "type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": lines},
            "properties": {
                "kind": "route",
                "type": tags.get("piste:type") or ("skitour" if tags["route"] == "ski" else ""),
                "difficulty": tags.get("piste:difficulty", ""),
                "name": tags.get("piste:name") or tags.get("name") or "",
                # So the map can find the whole line again (what it draws is cut into tiles).
                "osm": f"r{el.get('id', 0)}",
            },
        }
    return None


def to_geojson(elements: list[dict[str, Any]]) -> dict[str, Any]:
    feats: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for el in elements:
        key = (str(el.get("type")), int(el.get("id", 0)))
        if key in seen:
            continue
        seen.add(key)
        tags = el.get("tags") or {}
        name = tags.get("piste:name") or tags.get("name") or ""
        if el.get("type") == "relation":
            if (rel := _relation(el, tags)) is not None:
                feats.append(rel)
            continue
        if (place := _place(el, tags)) is not None:
            feats.append(place)
            continue
        if el.get("type") == "node" and tags.get("natural") == "peak":
            ele = _ele(tags)
            props: dict[str, Any] = {"kind": "peak", "name": name}
            if ele is not None:
                props["ele"] = ele
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                    "properties": props,
                }
            )
            continue
        if el.get("type") != "way" or not el.get("geometry"):
            continue
        coords = [[round(p["lon"], 6), round(p["lat"], 6)] for p in el["geometry"]]
        if len(coords) < 2:
            continue
        if tags.get("natural") == "glacier":
            if coords[0] == coords[-1] and len(coords) >= 4:
                feats.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [_closed(coords)]},
                        "properties": {
                            "kind": "glacier",
                            "name": tags.get("name", ""),
                            "osm": _osm_id(el),
                        },
                    }
                )
            continue
        if tags.get("natural") == "cliff":
            props = {"kind": "cliff", "name": tags.get("name", "")}
            coords = simplify(coords)
        elif "piste:type" in tags:
            ptype = tags["piste:type"]
            if ptype not in RUN_TYPES:
                continue
            props = {
                "kind": "run",
                "type": ptype,
                "difficulty": tags.get("piste:difficulty", ""),
                "name": name,
                "osm": f"w{el.get('id', 0)}",
            }
        elif "aerialway" in tags and tags["aerialway"] not in ("station", "pylon", "goods"):
            props = {"kind": "lift", "type": tags["aerialway"], "name": name}
        else:
            continue
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": feats}


def fetch_box(client: httpx.Client, box: tuple[float, float, float, float]) -> list[Any] | None:
    """One location's runs, lifts, peaks and features, from the first server that answers
    in full."""
    q = query([box])
    for url in OVERPASS:
        try:
            r = client.post(url, data={"data": q}, timeout=180)
            if r.status_code != 200:
                log.warning("overpass %s answered %s", url, r.status_code)
                continue
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("overpass %s failed: %s", url, e)
            continue
        # A timeout or memory limit still answers 200, with a remark and partial data.
        remark = str(data.get("remark", "")) if isinstance(data, dict) else ""
        if "error" in remark.lower():
            log.warning("overpass %s: %s", url, remark[:200])
            continue
        elements = data.get("elements") if isinstance(data, dict) else None
        if isinstance(elements, list):
            return elements
        log.warning("overpass %s answered without elements", url)
    return None


def refresh(
    path: Path,
    points: Iterable[tuple[float, float]],
    client: httpx.Client,
    *,
    now: float | None = None,
    force: bool = False,
    pause: float = 1.0,
) -> bool:
    """Fetch again if the file is missing, a week old (six hours if empty), or the locations
    changed. Returns whether it wrote a new file. Keeps the old file if Overpass fails."""
    bxs = boxes(points)
    key = json.dumps({"v": QUERY_VERSION, "boxes": bxs})
    meta = path.with_suffix(".meta.json")
    now = now or time.time()
    if not force and path.exists() and meta.exists():
        try:
            m = json.loads(meta.read_text())
            max_age = MAX_AGE_S if int(m.get("features", 0)) > 0 else EMPTY_MAX_AGE_S
            if m.get("key") == key and now - float(m.get("at", 0)) < max_age:
                return False
        except (ValueError, TypeError):
            pass
    if not bxs:
        return False
    # One small query per location: quicker for the servers, and well under their limits.
    elements: list[Any] = []
    for i, box in enumerate(bxs):
        if i and pause:
            time.sleep(pause)
        got = fetch_box(client, box)
        if got is None:
            log.warning("ski map data: no server answered for %s; keeping the old file", box)
            return False
        elements.extend(got)
    fc = to_geojson(elements)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(fc, separators=(",", ":")))
    tmp.replace(path)
    meta.write_text(json.dumps({"key": key, "at": now, "features": len(fc["features"])}))
    log.info("ski map data: %d runs, lifts, peaks and mountain features", len(fc["features"]))
    return True
