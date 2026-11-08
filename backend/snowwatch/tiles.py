"""A small caching proxy for the Map page's base map and ski-run tiles.

OpenTopoMap answers in ~0.5–1 s a tile and OpenSnowMap in ~0.5 s; from here a cached
tile comes back at once, and the long Cache-Control lets the browser (and Cloudflare)
keep it too. Esri's topo tiles have a lighter last row and column that would draw a
faint grid on the map; they're repaired once, as they enter the cache.

Tiles live under data/tiles/<layer>/<z>/<x>/<y>, and the nightly job drops ones
nobody has asked for in a while. Elevation tiles for 3D go straight from the browser
to AWS (fast, and large), so they aren't proxied.
"""

from __future__ import annotations

import contextlib
import io
import os
import threading
import time
from dataclasses import dataclass
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


def repair_edges(data: bytes) -> bytes:
    """Copy the second-last row and column over Esri's lighter last ones."""
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    im.paste(im.crop((0, h - 2, w, h - 1)), (0, h - 1))
    im.paste(im.crop((w - 2, 0, w - 1, h)), (w - 1, 0))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=88)
    return out.getvalue()


class TileCache:
    def __init__(self, root: Path, user_agent: str, client: httpx.Client | None = None) -> None:
        self.root = root
        self.client = client or httpx.Client(
            headers={"User-Agent": user_agent}, timeout=15, follow_redirects=True
        )
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def get(self, layer: str, z: int, x: int, y: int) -> tuple[bytes, str] | None:
        """The tile's bytes and media type, from the cache or upstream. None if it has none."""
        up = UPSTREAMS.get(layer)
        if up is None or not (0 <= z <= up.max_zoom) or not (0 <= x < 2**z and 0 <= y < 2**z):
            return None
        path = self.root / layer / str(z) / str(x) / str(y)
        key = f"{layer}/{z}/{x}/{y}"
        # One upstream fetch per tile even when several requests arrive together.
        with self._lock(key):
            if path.exists():
                os.utime(path)  # remember it was used, for pruning
                return path.read_bytes(), up.media_type
            url = up.urls[(x + y) % len(up.urls)].format(z=z, x=x, y=y)
            try:
                r = self.client.get(url)
            except httpx.HTTPError:
                return None
            if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
                return None
            data = r.content
            if up.fix_edges:
                with contextlib.suppress(OSError):  # keep the tile as it came
                    data = repair_edges(data)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        with self._guard:
            self._locks.pop(key, None)
        return data, up.media_type


def prune(root: Path, keep_days: int = KEEP_DAYS, now: float | None = None) -> int:
    """Remove tiles not asked for in `keep_days`. Returns how many went."""
    cutoff = (now or time.time()) - keep_days * 86400
    removed = 0
    if not root.exists():
        return 0
    for p in root.rglob("*"):
        if p.is_file() and p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)
            removed += 1
    return removed
