"""Recent satellite imagery for the map (docs/MAP-PLAN.md, B6).

Every six hours the worker looks, for each location, for the newest Sentinel-2 views
(Microsoft Planetary Computer) that actually see the ground there. A scene's own cloud
percentage covers a 110 km tile and says little about one valley (a "0 % cloud" scene
had no data at all at a test location), so each candidate is judged by its scene
classification layer (SCL) over a small square round the location: at least
`min_clear` of the pixels with data must be free of cloud and cloud shadow, and at most
`max_nodata` may have no data. The newest `keep` that pass go into
`data/sat/index.json`, which the API serves at /api/sat and which also lists the only
Sentinel-2 items the tile proxy will fetch (see snowwatch/tiles.py).

A Sentinel-2 pass is cut into 110 km MGRS tiles, each its own STAC item; a "scene" here
is one pass (a datatake): every item of it that covers the square. Its SCL crops are
merged, so a location on a tile edge still counts as covered.

The index also names the newest day of NASA GIBS's daily VIIRS mosaic that has imagery
over the map (today's is black until the afternoon pass is processed) and the newest
day of HLS (30 m Sentinel-2, about six days behind). Judged scenes are remembered in
`data/sat/checked.json`, so each refresh only reads the SCL of new passes.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import httpx
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from snowwatch.models import Location

log = logging.getLogger("snowwatch.sat")

PC = "https://planetarycomputer.microsoft.com/api"
STAC_SEARCH = f"{PC}/stac/v1/search"
PC_DATA = f"{PC}/data/v1"
COLLECTION = "sentinel-2-l2a"
GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
VIIRS = "VIIRS_NOAA20_CorrectedReflectance_TrueColor"
VIIRS_SNOW = "VIIRS_NOAA20_CorrectedReflectance_BandsM11-I2-I1"
HLS = "HLS_S30_Nadir_BRDF_Adjusted_Reflectance"

# The square judged round each location: 8 x 8 km at 64 x 64 pixels (~125 m each).
CROP_KM = 4.0
CROP_PX = 64
# SCL classes: 0 no data, 3 cloud shadow, 8 and 9 cloud, 10 thin cirrus, 11 snow.
NO_DATA = 0
CLOUDY = (3, 8, 9, 10)
SNOW = 11
# New passes judged per location per refresh (each is one to four small requests);
# the rest wait for the next refresh.
MAX_CHECKS = 24
# How long a judged pass is remembered (longer than the search window).
CHECKED_DAYS = 45

ITEM_ID = re.compile(r"S2[A-D]_MSIL2A_\d{8}T\d{6}_R\d{3}_T\d{2}[A-Z]{3}_\d{8}T\d{6}")
ATTRIBUTION = [
    "Contains modified Copernicus Sentinel data",
    "Microsoft Planetary Computer",
    "NASA GIBS (VIIRS, HLS)",
]

Quad = Annotated[list[float], Field(min_length=4, max_length=4)]


class SatItem(BaseModel):
    """One Sentinel-2 tile of a pass: its id for the tile proxy and its outline."""

    id: str
    bbox: Quad  # west, south, east, north


class SatScene(BaseModel):
    """One Sentinel-2 pass that sees the ground at a location."""

    id: str  # the pass (datatake), e.g. S2C_MSIL2A_20261110T182601_R127
    time: datetime
    platform: str  # Sentinel-2A, -2B or -2C
    clear_pct: int  # of the square round the location with data: no cloud or shadow
    snow_pct: int  # of the same: snow
    nodata_pct: int  # of the whole square
    items: list[SatItem]
    # GIBS has HLS (30 m, from this same pass) for its date: wider than the items.
    hls: bool = False


class SatLocation(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    scenes: list[SatScene]  # newest first
    checked_at: datetime | None = None
    error: str | None = None


class SatOut(BaseModel):
    """The map's recent satellite imagery: daily VIIRS, and clear Sentinel-2 scenes per
    location (newest first)."""

    generated_at: datetime | None = None
    viirs_date: str | None = None  # the newest day of daily VIIRS with imagery here
    hls_date: str | None = None  # the newest day of HLS on GIBS
    days: int = 30  # how far back scenes are looked for
    min_clear_pct: int = 70
    locations: list[SatLocation] = []
    attribution: list[str] = ATTRIBUTION


# --- judging a pass ---------------------------------------------------------------


@dataclass(frozen=True)
class Look:
    clear: float  # share of pixels with data that are free of cloud and shadow
    nodata: float  # share of all pixels without data
    snow: float  # share of pixels with data that are snow


def merge_crops(crops: Iterable[np.ndarray]) -> np.ndarray:
    """One SCL square from several tiles' crops: each pixel from the first that has data.

    A crop is Planetary Computer's `.npy` answer: (2, h, w), the SCL class then a mask
    (0 where the tile has no data)."""
    out: np.ndarray | None = None
    for a in crops:
        scl = np.where(a[1] > 0, a[0], NO_DATA).astype(np.uint8)
        out = scl if out is None else np.where(out == NO_DATA, scl, out)
    if out is None:
        raise ValueError("no crops")
    return out


def judge(scl: np.ndarray) -> Look:
    valid = scl != NO_DATA
    n = int(valid.sum())
    if n == 0:
        return Look(clear=0.0, nodata=1.0, snow=0.0)
    cloudy = int(np.isin(scl, CLOUDY).sum())
    return Look(
        clear=1 - cloudy / n,
        nodata=1 - n / scl.size,
        snow=int((scl == SNOW).sum()) / n,
    )


def crop_box(lat: float, lon: float, km: float = CROP_KM) -> tuple[float, float, float, float]:
    """West, south, east, north of the square round a point."""
    dlat = km / 111.32
    dlon = km / (111.32 * max(0.1, math.cos(math.radians(lat))))
    return (round(lon - dlon, 5), round(lat - dlat, 5), round(lon + dlon, 5), round(lat + dlat, 5))


# --- passes -----------------------------------------------------------------------


@dataclass
class Pass:
    id: str
    time: datetime
    platform: str
    items: list[SatItem] = field(default_factory=list)


def pass_id(item_id: str) -> str:
    """The datatake an item belongs to: satellite, product, sensing time, orbit."""
    return "_".join(item_id.split("_")[:4])


def group_passes(features: Sequence[dict[str, Any]]) -> list[Pass]:
    """STAC items grouped by pass, newest first. An MGRS tile processed twice keeps its
    newest processing."""
    by_pass: dict[str, Pass] = {}
    tiles: dict[tuple[str, str], str] = {}
    for f in features:
        fid = str(f.get("id", ""))
        if not ITEM_ID.fullmatch(fid):
            continue
        props = f.get("properties") or {}
        try:
            t = datetime.fromisoformat(str(props["datetime"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        bbox = f.get("bbox") or []
        if len(bbox) != 4:
            continue
        pid = pass_id(fid)
        tile = fid.split("_")[4]
        prev = tiles.get((pid, tile))
        if prev is not None and prev >= fid:
            continue
        p = by_pass.setdefault(pid, Pass(pid, t, str(props.get("platform") or _platform(fid)), []))
        if prev is not None:
            p.items = [i for i in p.items if i.id != prev]
        tiles[(pid, tile)] = fid
        p.items.append(SatItem(id=fid, bbox=[round(float(v), 5) for v in bbox]))
    return sorted(by_pass.values(), key=lambda p: p.time, reverse=True)


def _platform(item_id: str) -> str:
    return f"Sentinel-2{item_id[2]}"


def search(
    client: httpx.Client, lat: float, lon: float, start: datetime, end: datetime
) -> list[Pass]:
    w, s, e, n = crop_box(lat, lon)
    body = {
        "collections": [COLLECTION],
        "bbox": [w, s, e, n],
        "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
        "limit": 200,
        "sortby": [{"field": "datetime", "direction": "desc"}],
        "fields": {
            "include": ["id", "bbox", "properties.datetime", "properties.platform"],
            "exclude": ["assets", "links", "geometry"],
        },
    }
    r = client.post(STAC_SEARCH, json=body, timeout=40)
    r.raise_for_status()
    return group_passes(r.json().get("features") or [])


def scl_crop(client: httpx.Client, item: str, lat: float, lon: float) -> np.ndarray | None:
    """The SCL square round a point from one item, or None where the item doesn't reach."""
    w, s, e, n = crop_box(lat, lon)
    url = f"{PC_DATA}/item/bbox/{w},{s},{e},{n}/{CROP_PX}x{CROP_PX}.npy"
    r = client.get(
        url, params={"collection": COLLECTION, "item": item, "assets": "SCL"}, timeout=40
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    a: np.ndarray = np.load(io.BytesIO(r.content), allow_pickle=False)
    if a.ndim != 3 or a.shape[0] != 2:
        raise ValueError(f"unexpected SCL crop shape {a.shape}")
    return a


def look_at(client: httpx.Client, p: Pass, lat: float, lon: float) -> Look:
    """Judge a pass at a point, reading as few of its tiles as it takes to cover it."""
    crops: list[np.ndarray] = []
    for it in p.items:
        a = scl_crop(client, it.id, lat, lon)
        if a is None:
            continue
        crops.append(a)
        if judge(merge_crops(crops)).nodata == 0:
            break
    if not crops:
        return Look(clear=0.0, nodata=1.0, snow=0.0)
    return judge(merge_crops(crops))


# --- GIBS -------------------------------------------------------------------------


def latest_day(client: httpx.Client, layer: str, matrix: str) -> str | None:
    """The newest day GIBS has for a layer (its WMTS time domain)."""
    today = datetime.now(UTC).date()
    url = (
        f"{GIBS}/1.0.0/{layer}/default/{matrix}/all/"
        f"{today - timedelta(days=60)}--{today + timedelta(days=1)}.xml"
    )
    r = client.get(url, timeout=30)
    r.raise_for_status()
    m = re.findall(r"<Domain>([^<]*)</Domain>", r.text)
    days = re.findall(r"\d{4}-\d{2}-\d{2}", m[-1]) if m else []
    return max(days) if days else None


def tile_xy(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def has_imagery(data: bytes) -> bool:
    """A VIIRS tile with imagery, not the black of a day not yet processed."""
    try:
        a = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.uint16)
    except OSError:
        return False
    return float((a.sum(axis=2) < 15).mean()) < 0.5


def viirs_day(client: httpx.Client, lat: float, lon: float, today: date) -> str | None:
    """The newest of the last four days whose daily VIIRS mosaic has imagery here."""
    x, y = tile_xy(lat, lon, 6)
    for back in range(4):
        d = today - timedelta(days=back)
        url = f"{GIBS}/{VIIRS}/default/{d}/GoogleMapsCompatible_Level9/6/{y}/{x}.jpeg"
        try:
            r = client.get(url, timeout=30)
        except httpx.HTTPError:
            continue
        if r.status_code == 200 and has_imagery(r.content):
            return d.isoformat()
    return None


# --- the index --------------------------------------------------------------------


@dataclass
class SatResult:
    locations: int = 0
    scenes: int = 0
    checked: int = 0
    errors: list[str] = field(default_factory=list)


def read_index(path: Path) -> SatOut | None:
    try:
        return SatOut.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _read_checked(path: Path) -> dict[str, dict[str, list[float]]]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _spot_key(loc_id: str, lat: float, lon: float) -> str:
    # A location that moves is judged afresh.
    return f"{loc_id}@{lat:.3f},{lon:.3f}"


def allowed_items(index: SatOut | None) -> set[str]:
    """The Sentinel-2 items the tile proxy may fetch: those in the index."""
    if index is None:
        return set()
    return {it.id for loc in index.locations for sc in loc.scenes for it in sc.items}


def refresh(
    sat_dir: Path,
    client: httpx.Client,
    locations: Sequence[Location],
    *,
    days: int = 30,
    min_clear: float = 0.7,
    max_nodata: float = 0.1,
    keep: int = 3,
    now: datetime | None = None,
) -> SatResult:
    """Find each location's newest clear scenes and write the index. A location whose
    search fails keeps the scenes it had."""
    now = now or datetime.now(UTC)
    start = now - timedelta(days=days)
    out = SatResult()
    index_path = sat_dir / "index.json"
    checked_path = sat_dir / "checked.json"
    old = read_index(index_path)
    old_by_id = {loc.id: loc for loc in old.locations} if old else {}
    checked = _read_checked(checked_path)
    cutoff = (now - timedelta(days=CHECKED_DAYS)).timestamp()
    spots: list[SatLocation] = []
    keep_keys: set[str] = set()

    try:
        hls_date = latest_day(client, HLS, "GoogleMapsCompatible_Level12")
    except (httpx.HTTPError, ValueError) as e:
        out.errors.append(f"HLS dates: {e}")
        hls_date = old.hls_date if old else None

    for loc in locations:
        mid = loc.band("mid")
        lat, lon = mid.lat, mid.lon
        key = _spot_key(loc.id, lat, lon)
        keep_keys.add(key)
        seen = checked.setdefault(key, {})
        spot = SatLocation(id=loc.id, name=loc.name, lat=lat, lon=lon, scenes=[], checked_at=now)
        try:
            passes = search(client, lat, lon, start, now)
            fresh = 0
            for p in passes:
                if len(spot.scenes) >= keep:
                    break
                got = seen.get(p.id)
                if got is None:
                    if fresh >= MAX_CHECKS:
                        continue
                    fresh += 1
                    out.checked += 1
                    look = look_at(client, p, lat, lon)
                    got = [look.clear, look.nodata, look.snow, p.time.timestamp()]
                    seen[p.id] = got
                look = Look(clear=got[0], nodata=got[1], snow=got[2])
                if look.clear < min_clear or look.nodata > max_nodata:
                    continue
                spot.scenes.append(
                    SatScene(
                        id=p.id,
                        time=p.time,
                        platform=p.platform,
                        clear_pct=round(look.clear * 100),
                        snow_pct=round(look.snow * 100),
                        nodata_pct=round(look.nodata * 100),
                        items=p.items,
                        hls=hls_date is not None and p.time.date().isoformat() <= hls_date,
                    )
                )
        except (httpx.HTTPError, ValueError) as e:
            msg = f"{loc.id}: {type(e).__name__}: {e}"
            out.errors.append(msg)
            log.warning("satellite scenes for %s failed: %s", loc.id, e)
            prev = old_by_id.get(loc.id)
            spot.scenes = list(prev.scenes) if prev else []
            spot.checked_at = prev.checked_at if prev else None
            spot.error = "Couldn't look for new scenes; showing the last ones found."
        spots.append(spot)
        out.scenes += len(spot.scenes)

    # Forget passes older than the search window could return, and moved locations.
    checked = {
        k: {pid: v for pid, v in by.items() if len(v) > 3 and v[3] >= cutoff}
        for k, by in checked.items()
        if k in keep_keys
    }
    lat0 = sum(s.lat for s in spots) / len(spots) if spots else 45.0
    lon0 = sum(s.lon for s in spots) / len(spots) if spots else -118.0
    viirs = viirs_day(client, lat0, lon0, now.date())
    if viirs is None:
        out.errors.append("VIIRS: no day with imagery in the last four")
        viirs = old.viirs_date if old else None

    index = SatOut(
        generated_at=now,
        viirs_date=viirs,
        hls_date=hls_date,
        days=days,
        min_clear_pct=round(min_clear * 100),
        locations=spots,
    )
    _write(index_path, index.model_dump_json())
    _write(checked_path, json.dumps(checked, separators=(",", ":")))
    out.locations = len(spots)
    return out
