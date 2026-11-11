"""Avalanche danger zones for the whole map, as published (docs/MAP-PLAN.md, B7).

The worker writes every forecast zone in the map's box to `data/avalanche/zones.geojson`:
avalanche.org's map layer for the US (with each rated zone's product, so its problems
are known) and Avalanche Canada's areas and products. The file holds the forecasts as
fetched; the API applies expiry against the clock on every request (`zones_out`), the
same rule as for locations: an expired forecast shows as Expired, never as current.

`config/treeline.yaml` holds the approximate treeline band the map uses to turn
"alpine / treeline / below treeline" into elevations. It's served with the zones and
matched in the browser, where the spot in question is known.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from snowwatch.avalanche import (
    AvalancheDoc,
    AvalancheView,
    Memo,
    _level,
    fetch_once,
    parse_ca,
    parse_us,
    safe_zone,
    view,
)
from snowwatch.geo import bbox
from snowwatch.http import Fetcher, FetchError
from snowwatch.models import Location
from snowwatch.sources import avalanche_ca, avalanche_us

log = logging.getLogger("snowwatch.avalanche")

# Coordinates are kept to 4 decimals (~10 m): zone lines are drawn by hand at far
# coarser scales, and it keeps the file small.
DIGITS = 4
SPOT_KM = 40.0  # an owner's treeline numbers for a location apply this far from it

Box = tuple[float, float, float, float]  # south, west, north, east
Pair = Annotated[list[float], Field(min_length=2, max_length=2)]
Quad = Annotated[list[float], Field(min_length=4, max_length=4)]


# --- treeline -------------------------------------------------------------------


class TreelineRule(BaseModel):
    """Where the treeline band is: the first rule whose conditions all match wins."""

    name: str
    band: Pair  # bottom and top of the treeline band, metres
    center: str | None = None  # avalanche center id (avcan for Avalanche Canada)
    zone: str | None = None  # forecast zone name, any case
    box: Quad | None = None  # south, west, north, east

    @field_validator("band")
    @classmethod
    def _ordered(cls, v: list[float]) -> list[float]:
        if not 0 <= v[0] < v[1] <= 9000:
            raise ValueError("band is [bottom, top] in metres, bottom below top")
        return v


class TreelineConfig(BaseModel):
    rules: list[TreelineRule] = Field(min_length=1)
    locations: dict[str, Pair] = {}

    @field_validator("rules")
    @classmethod
    def _catch_all(cls, v: list[TreelineRule]) -> list[TreelineRule]:
        last = v[-1]
        if last.center or last.zone or last.box:
            raise ValueError("the last treeline rule must have no conditions (the default)")
        return v


class TreelineSpot(BaseModel):
    """The owner's treeline numbers near one location."""

    location_id: str
    name: str
    lat: float
    lon: float
    band: Pair


DEFAULT_TREELINE = TreelineConfig(rules=[TreelineRule(name="Default", band=[1500, 2000])])
_treeline_cache: dict[Path, tuple[float, TreelineConfig]] = {}


def load_treeline(path: Path) -> TreelineConfig:
    """The treeline file, re-read when it changes; the default band if it's missing."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return DEFAULT_TREELINE
    cached = _treeline_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    cfg = TreelineConfig.model_validate(yaml.safe_load(path.read_text()) or {})
    _treeline_cache[path] = (mtime, cfg)
    return cfg


def treeline_spots(cfg: TreelineConfig, locations: Iterable[Location]) -> list[TreelineSpot]:
    by_id = {loc.id: loc for loc in locations}
    out = []
    for loc_id, band in cfg.locations.items():
        loc = by_id.get(loc_id)
        if loc is None:
            log.warning("treeline.yaml names an unknown location %r", loc_id)
            continue
        mid = loc.band("mid")
        out.append(
            TreelineSpot(location_id=loc.id, name=loc.name, lat=mid.lat, lon=mid.lon, band=band)
        )
    return out


# --- what the API serves --------------------------------------------------------


class ZoneProps(BaseModel):
    id: str  # provider:zone, e.g. nac:2651
    tz: str
    today: str  # today's date in the zone's time zone
    view: AvalancheView  # `location_id` holds the zone id


class ZoneFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: dict[str, Any]
    properties: ZoneProps


class ZonesOut(BaseModel):
    """Every forecast zone in the map's box, as published, with expiry applied now."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    generated_at: str | None
    features: list[ZoneFeature]
    treeline: list[TreelineRule]
    treeline_spots: list[TreelineSpot]
    spot_km: float = SPOT_KM
    problem_slope_deg: int = 30  # the problems layer's lowest slope, until the viewer picks


def zones_out(
    data: Mapping[str, Any] | None,
    now: datetime,
    treeline: TreelineConfig,
    spots: list[TreelineSpot],
    problem_slope_deg: int = 30,
) -> ZonesOut:
    features = []
    for f in (data or {}).get("features") or []:
        props = f.get("properties") or {}
        try:
            doc = AvalancheDoc.model_validate(props["doc"])
        except (KeyError, ValueError):
            continue
        tz = safe_zone(props.get("tz"))
        zid = str(f.get("id"))
        features.append(
            ZoneFeature(
                id=zid,
                geometry=f["geometry"],
                properties=ZoneProps(
                    id=zid,
                    tz=tz.key,
                    today=now.astimezone(tz).date().isoformat(),
                    view=view(zid, doc, now, tz),
                ),
            )
        )
    return ZonesOut(
        generated_at=(data or {}).get("generated_at"),
        features=features,
        treeline=treeline.rules,
        treeline_spots=spots,
        problem_slope_deg=problem_slope_deg,
    )


# --- building the file ------------------------------------------------------------


def _round(coords: Any) -> Any:
    if coords and isinstance(coords[0], int | float):
        return [round(coords[0], DIGITS), round(coords[1], DIGITS)]
    return [_round(c) for c in coords]


def _ring(ring: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for p in ring:
        if not out or p != out[-1]:
            out.append(p)
    return out


def tidy(geometry: Mapping[str, Any]) -> dict[str, Any] | None:
    """Rounded (multi)polygon without repeated points; None for anything else."""
    kind = geometry.get("type")
    if kind not in ("Polygon", "MultiPolygon"):
        return None
    polys = [geometry["coordinates"]] if kind == "Polygon" else geometry["coordinates"]
    out = []
    for poly in polys:
        rings = [_ring(_round(r)) for r in poly]
        rings = [r for r in rings if len(r) >= 4]
        if rings:
            out.append(rings)
    if not out:
        return None
    return {"type": "MultiPolygon", "coordinates": out}


def overlaps(geometry: Mapping[str, Any], box: Box) -> bool:
    b = bbox(dict(geometry))
    if b is None:
        return False
    south, west, north, east = box
    return b[0] <= east and b[2] >= west and b[1] <= north and b[3] >= south


@dataclass
class ZonesResult:
    us: int = 0
    ca: int = 0
    products: int = 0
    errors: list[str] = field(default_factory=list)


def _feature(zid: str, geometry: dict[str, Any], tz: str, doc: AvalancheDoc) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": zid,
        "geometry": geometry,
        "properties": {"tz": tz, "doc": doc.model_dump(mode="json")},
    }


def us_zones(
    fetcher: Fetcher, box: Box, memo: Memo, out: ZonesResult
) -> list[dict[str, Any]] | None:
    """avalanche.org's zones in the box; each rated zone with its full product.

    One product often covers several zones (CAIC's covers seven), so a product
    fetched for one zone serves every zone it lists. None if the map layer failed.
    """
    try:
        layer = fetch_once(fetcher, avalanche_us.map_layer_request(), memo)
    except FetchError as e:
        out.errors.append(f"avalanche.org map layer: {e}")
        return None
    feats = []
    for f in layer.get("features") or []:
        geom = tidy(f.get("geometry") or {})
        if geom is not None and overlaps(geom, box):
            feats.append((str(f.get("id")), f, geom))
    products: dict[str, Any] = {}
    for zid, f, _ in feats:
        props = f.get("properties") or {}
        rated = _level(props.get("danger_level")) is not None and not props.get("off_season")
        center = props.get("center_id")
        if not rated or not center or zid in products:
            continue
        try:
            product = fetch_once(fetcher, avalanche_us.product_request(str(center), zid), memo)
        except FetchError as e:
            out.errors.append(f"avalanche.org {center} {zid}: {e}")
            continue
        if not isinstance(product, dict):
            continue
        out.products += 1
        products[zid] = product
        for z in product.get("forecast_zone") or []:
            products.setdefault(str(z.get("id")), product)
    zones = []
    for zid, f, geom in feats:
        props = f.get("properties") or {}
        tz = safe_zone(props.get("timezone"), "America/Denver")
        try:
            doc = parse_us(products.get(zid), f, zid, tz)
        except Exception as e:  # one odd product must not stop the map
            log.exception("avalanche zone %s failed", zid)
            out.errors.append(f"avalanche.org zone {zid}: {type(e).__name__}: {e}")
            continue
        zones.append(_feature(f"nac:{zid}", geom, tz.key, doc))
    out.us = len(zones)
    return zones


def ca_zones(
    fetcher: Fetcher, box: Box, memo: Memo, out: ZonesResult
) -> list[dict[str, Any]] | None:
    """Avalanche Canada's areas in the box, each with its product. None on failure."""
    try:
        areas = fetch_once(fetcher, avalanche_ca.areas_request(), memo)
        prods = fetch_once(fetcher, avalanche_ca.products_request(), memo)
    except FetchError as e:
        out.errors.append(f"Avalanche Canada: {e}")
        return None
    by_area = {str((p.get("area") or {}).get("id")): p for p in prods or [] if isinstance(p, dict)}
    zones = []
    for f in areas.get("features") or []:
        aid = str(f.get("id"))
        geom = tidy(f.get("geometry") or {})
        if geom is None or not overlaps(geom, box) or aid not in by_area:
            continue
        try:
            product = by_area[aid]
            doc = parse_ca(product)
            tz = safe_zone((product.get("report") or {}).get("timezone"), "America/Vancouver")
        except Exception as e:
            log.exception("Avalanche Canada area %s failed", aid)
            out.errors.append(f"Avalanche Canada area {aid}: {type(e).__name__}: {e}")
            continue
        zones.append(_feature(f"avcan:{aid}", geom, tz.key, doc))
    out.ca = len(zones)
    return zones


def map_box(region: Box, locations: Iterable[Location]) -> Box:
    """The map's box (config `map.region`), widened to take in every location."""
    south, west, north, east = region
    for loc in locations:
        for b in loc.bands[:1]:
            south, north = min(south, b.lat - 1), max(north, b.lat + 1)
            west, east = min(west, b.lon - 1), max(east, b.lon + 1)
    return south, west, north, east


def read_zones(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def refresh_zones(path: Path, fetcher: Fetcher, box: Box, memo: Memo | None = None) -> ZonesResult:
    """Fetch every zone in the box and write the file. A provider that fails keeps
    its zones from the last file, so one outage doesn't empty half the map."""
    memo = {} if memo is None else memo
    out = ZonesResult()
    old = read_zones(path) or {}
    old_feats = old.get("features") or []
    us = us_zones(fetcher, box, memo, out)
    ca = ca_zones(fetcher, box, memo, out)
    if us is None:
        us = [f for f in old_feats if str(f.get("id", "")).startswith("nac:")]
    if ca is None:
        ca = [f for f in old_feats if str(f.get("id", "")).startswith("avcan:")]
    data = {
        "type": "FeatureCollection",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "box": list(box),
        "features": us + ca,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    os.replace(tmp, path)
    for err in out.errors:
        log.warning(err)
    return out
