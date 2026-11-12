"""A small caching proxy for the Map page's base map and ski-run tiles.

OpenTopoMap answers in ~0.5–1 s a tile and OpenSnowMap in ~0.5 s; from here a cached
tile comes back at once, and the long Cache-Control lets the browser (and Cloudflare)
keep it too. Esri's topo tiles have a lighter last row and column that would draw a
faint grid on the map; they're repaired once, as they enter the cache.

Tiles live under data/tiles/<layer>/<z>/<x>/<y>. The cache has a size cap
(TILES_MAX_MB): once full it still serves tiles but stops storing new ones, and the
nightly job drops tiles nobody has asked for in a while, then the least recently
used ones until it is back under the cap. At most a few upstream fetches run at
once. Elevation tiles go straight from the browser to Mapterhorn (fast, and large),
so they aren't proxied. NASA GIBS's daily satellite mosaic is proxied the same way, under
data/tiles/gibs/.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from PIL import Image


@dataclass(frozen=True)
class Upstream:
    urls: tuple[str, ...]
    max_zoom: int
    media_type: str
    fix_edges: bool = False


UPSTREAMS: dict[str, Upstream] = {
    "otm": Upstream(
        tuple(f"https://{s}.tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png" for s in "abc"),
        17,
        "image/png",
    ),
    "pistes": Upstream(("https://tiles.opensnowmap.org/pistes/{z}/{x}/{y}.png",), 18, "image/png"),
    # Satellite imagery for the Satellite style, with place names and borders on top.
    "sat": Upstream(
        (
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/"
            "tile/{z}/{y}/{x}",
        ),
        18,
        "image/jpeg",
    ),
    "satlabels": Upstream(
        (
            "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/"
            "World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        ),
        18,
        "image/png",
    ),
    "esri": Upstream(
        (
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/"
            "tile/{z}/{y}/{x}",
        ),
        19,
        "image/jpeg",
        fix_edges=True,
    ),
}

KEEP_DAYS = 45
MAX_TILE_BYTES = 2_000_000  # a real 256 px tile is well under this
UPSTREAM_AT_ONCE = 6


def repair_edges(data: bytes) -> bytes:
    """Copy the second-last row and column over Esri's lighter last ones."""
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    im.paste(im.crop((0, h - 2, w, h - 1)), (0, h - 1))
    im.paste(im.crop((w - 2, 0, w - 1, h)), (w - 1, 0))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=88)
    return out.getvalue()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def cache_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0


class TileCache:
    def __init__(
        self,
        root: Path,
        user_agent: str,
        client: httpx.Client | None = None,
        *,
        max_bytes: int | None = None,
    ) -> None:
        self.root = root
        self.max_bytes = max_bytes
        self.client = client or httpx.Client(
            headers={"User-Agent": user_agent}, timeout=15, follow_redirects=True
        )
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._upstream = threading.BoundedSemaphore(UPSTREAM_AT_ONCE)
        self._size: int | None = None  # bytes on disk, counted on the first miss

    def _path(self, layer: str, z: int, x: int, y: int) -> Path | None:
        up = UPSTREAMS.get(layer)
        if up is None or not (0 <= z <= up.max_zoom) or not (0 <= x < 2**z and 0 <= y < 2**z):
            return None
        return self.root / layer / str(z) / str(x) / str(y)

    def cached(self, layer: str, z: int, x: int, y: int) -> bool:
        path = self._path(layer, z, x, y)
        return path is not None and path.exists()

    def _store(self, path: Path, data: bytes) -> None:
        """Keep a fetched file unless the cache is full (the nightly prune makes room)."""
        with self._guard:
            if self._size is None:
                self._size = cache_bytes(self.root)
            if self.max_bytes is not None and self._size + len(data) > self.max_bytes:
                return
            self._size += len(data)
        _write_atomic(path, data)

    def fetch(self, url: str) -> bytes | None:
        """One upstream file, or None. Limits how many run at once and how big they get."""
        with self._upstream:
            try:
                r = self.client.get(url)
            except httpx.HTTPError:
                return None
        if r.status_code != 200 or len(r.content) > MAX_TILE_BYTES:
            return None
        return r.content

    def _lock(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def get(self, layer: str, z: int, x: int, y: int) -> tuple[bytes, str] | None:
        """The tile's bytes and media type, from the cache or upstream. None if it has none."""
        path = self._path(layer, z, x, y)
        if path is None:
            return None
        up = UPSTREAMS[layer]
        url = up.urls[(x + y) % len(up.urls)].format(z=z, x=x, y=y)
        data = self.through(path, url, up.fix_edges)
        return None if data is None else (data, up.media_type)

    def through(self, path: Path, url: str, fix_edges: bool = False) -> bytes | None:
        """A file from the cache at `path`, else fetched from `url` (an image) and kept."""
        key = str(path.relative_to(self.root))
        # One upstream fetch per tile even when several requests arrive together.
        with self._lock(key):
            if path.exists():
                os.utime(path)  # remember it was used, for pruning
                return path.read_bytes()
            with self._upstream:
                try:
                    r = self.client.get(url)
                except httpx.HTTPError:
                    return None
            if (
                r.status_code != 200
                or not r.headers.get("content-type", "").startswith("image/")
                or len(r.content) > MAX_TILE_BYTES
            ):
                return None
            data = r.content
            if fix_edges:
                with contextlib.suppress(OSError):  # keep the tile as it came
                    data = repair_edges(data)
            self._store(path, data)
        with self._guard:
            self._locks.pop(key, None)
        return data


# ---- Recent satellite: NASA GIBS's daily VIIRS mosaic (docs/MAP-PLAN.md, B6) ------------
# (Sentinel-2 views are drawn by the worker and served from data/sat/views/.)


@dataclass(frozen=True)
class GibsLayer:
    matrix: str
    ext: str
    max_zoom: int
    media_type: str


GIBS_URL = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
GIBS_LAYERS = {
    "VIIRS_NOAA20_CorrectedReflectance_TrueColor": GibsLayer(
        "GoogleMapsCompatible_Level9", "jpeg", 9, "image/jpeg"
    ),
    "VIIRS_NOAA20_CorrectedReflectance_BandsM11-I2-I1": GibsLayer(
        "GoogleMapsCompatible_Level9", "jpeg", 9, "image/jpeg"
    ),
}
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _xy_ok(z: int, x: int, y: int) -> bool:
    n: int = 2**z
    return 0 <= x < n and 0 <= y < n


def gibs_path(
    cache: TileCache, layer: str, day: str, z: int, x: int, y: int, today: date | None = None
) -> Path | None:
    """Where a GIBS tile is cached; None unless it's a layer, day and tile the proxy serves."""
    g = GIBS_LAYERS.get(layer)
    if g is None or not DAY.fullmatch(day) or not (0 <= z <= g.max_zoom) or not _xy_ok(z, x, y):
        return None
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return None
    today = today or datetime.now(UTC).date()
    if not (date(2015, 1, 1) <= d <= today + timedelta(days=1)):
        return None
    return cache.root / "gibs" / layer / day / str(z) / str(x) / str(y)


def gibs_tile(
    cache: TileCache, layer: str, day: str, z: int, x: int, y: int, today: date | None = None
) -> tuple[bytes, str] | None:
    """A tile of one of GIBS's daily layers for one day (not in the future)."""
    path = gibs_path(cache, layer, day, z, x, y, today)
    if path is None:
        return None
    g = GIBS_LAYERS[layer]
    data = cache.through(path, f"{GIBS_URL}/{layer}/default/{day}/{g.matrix}/{z}/{y}/{x}.{g.ext}")
    return None if data is None else (data, g.media_type)


GLYPHS = "https://demotiles.maplibre.org/font/{stack}/{range}.pbf"
FONTS = {"Open Sans Semibold", "Noto Sans Regular"}


def glyphs(cache: TileCache, stack: str, rng: str) -> bytes | None:
    """Map label fonts (MapLibre glyph ranges), cached like tiles."""
    if stack not in FONTS or not re.fullmatch(r"\d{1,5}-\d{1,5}", rng):
        return None
    path = cache.root / "glyphs" / stack.replace(" ", "_") / f"{rng}.pbf"
    if path.exists():
        return path.read_bytes()
    data = cache.fetch(GLYPHS.format(stack=stack.replace(" ", "%20"), range=rng))
    if data is None:
        return None
    cache._store(path, data)
    return data


def prune(
    root: Path,
    keep_days: int = KEEP_DAYS,
    now: float | None = None,
    max_bytes: int | None = None,
) -> int:
    """Remove tiles not asked for in `keep_days`, then the least recently used ones until
    the cache is under 90% of `max_bytes`. Returns how many went."""
    if not root.exists():
        return 0
    cutoff = (now or time.time()) - keep_days * 86400
    removed = 0
    kept: list[tuple[float, int, Path]] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        st = p.stat()
        if st.st_mtime < cutoff or p.name.endswith(".tmp"):
            p.unlink(missing_ok=True)
            removed += 1
        else:
            kept.append((st.st_mtime, st.st_size, p))
    if max_bytes is not None:
        total = sum(size for _, size, _ in kept)
        for _, size, p in sorted(kept, key=lambda k: k[0]):
            if total <= max_bytes * 0.9:
                break
            p.unlink(missing_ok=True)
            total -= size
            removed += 1
    for d in sorted((d for d in root.rglob("*") if d.is_dir()), reverse=True):
        with contextlib.suppress(OSError):
            d.rmdir()  # only empty ones go
    return removed
