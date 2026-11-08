"""Ski runs, lifts and peaks around the locations, from OpenStreetMap, for the Map page.

The worker asks Overpass once a week (or when the locations change) for the runs
(`piste:type`), lifts (`aerialway`) and named peaks in a box around each location,
and saves them as one small GeoJSON file. The map draws them as vector lines with
names that follow the runs and stay upright in 3D, which picture tiles can't do.

Coverage is whatever OSM mappers have added: resorts are usually complete; ski-touring
and backcountry lines (`piste:type=skitour`) are hit and miss.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("snowwatch.osm")

OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
MAX_AGE_S = 7 * 86400
# Around each location: ~35 x 35 km, enough for the resort and the touring nearby.
PAD_LAT = 0.16
PAD_LON = 0.24
RUN_TYPES = {"downhill", "skitour", "backcountry", "nordic", "sled", "hike", "snow_park"}


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
    parts = []
    for s, w, n, e in bxs:
        b = f"({s},{w},{n},{e})"
        parts.append(f'way["piste:type"]{b};way["aerialway"]{b};node["natural"="peak"]["name"]{b};')
    return f"[out:json][timeout:120];({''.join(parts)});out tags geom;"


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
        if el.get("type") == "node" and tags.get("natural") == "peak":
            try:
                ele = round(float(str(tags.get("ele", "")).split()[0].replace(",", "")))
            except (ValueError, IndexError):
                ele = None
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
        if "piste:type" in tags:
            ptype = tags["piste:type"]
            if ptype not in RUN_TYPES:
                continue
            props = {
                "kind": "run",
                "type": ptype,
                "difficulty": tags.get("piste:difficulty", ""),
                "name": name,
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


def refresh(
    path: Path,
    points: Iterable[tuple[float, float]],
    client: httpx.Client,
    *,
    now: float | None = None,
    force: bool = False,
) -> bool:
    """Fetch again if the file is missing, a week old, or the locations changed.
    Returns whether it wrote a new file. Keeps the old file if Overpass fails."""
    bxs = boxes(points)
    key = json.dumps(bxs)
    meta = path.with_suffix(".meta.json")
    now = now or time.time()
    if not force and path.exists() and meta.exists():
        try:
            m = json.loads(meta.read_text())
            if m.get("key") == key and now - float(m.get("at", 0)) < MAX_AGE_S:
                return False
        except (ValueError, TypeError):
            pass
    if not bxs:
        return False
    q = query(bxs)
    data = None
    for url in OVERPASS:
        try:
            r = client.post(url, data={"data": q}, timeout=180)
            if r.status_code == 200:
                data = r.json()
                break
            log.warning("overpass %s answered %s", url, r.status_code)
        except (httpx.HTTPError, ValueError) as e:
            log.warning("overpass %s failed: %s", url, e)
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        return False
    fc = to_geojson(data["elements"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(fc, separators=(",", ":")))
    tmp.replace(path)
    meta.write_text(json.dumps({"key": key, "at": now, "features": len(fc["features"])}))
    log.info("ski map data: %d runs, lifts and peaks", len(fc["features"]))
    return True
