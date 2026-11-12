"""Drawing the map's recent satellite views (docs/MAP-PLAN.md, B6).

Every view is drawn once, by the worker, as a 24 x 24 km picture at Sentinel-2's own
10 m (2,400 pixels a side, in Web Mercator), then cut into the map's 512 px tiles for
zooms 9-13 under `data/sat/views/<view>/<natural|snow>/`. The browser then loads one
layer of small finished tiles: nothing is fetched or drawn upstream while it pans.

- A **scene** view is one pass as it is.
- A **stitched** view takes each pixel from the pass `sat.stitch` chose for that part of
  the area (the newest that saw the ground there) if that pass saw it clearly; failing
  that (a cloud gap inside the part), from the newest other chosen pass that did.
  Cloud, cloud shadow and an 80 m margin round them come from each pass's scene
  classification at 20 m. The parts follow the 250 m grid's boundaries, smoothed.

Pictures come from Planetary Computer's tiler as four 1,200 px quarters per tile of a
pass (a whole 2,400 px picture can time out), already in Web Mercator, and are kept in
`data/sat/crops/` (a pass never changes), so a refresh only fetches new passes.
"""

from __future__ import annotations

import hashlib
import io
import logging
import math
import shutil
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx
import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from snowwatch.maps.sat import Pass

log = logging.getLogger("snowwatch.sat")

PC_BBOX = "https://planetarycomputer.microsoft.com/api/data/v1/item/bbox"
# Bumped whenever the drawing changes, so every view is drawn afresh (new names).
RENDER = 5
PX = 2400  # pixels a side of a view's picture: 24 km at 10 m
HALF = PX // 2
TILE = 512
ZOOMS = range(9, 14)  # zoom 13 is ~6.5 m a pixel here, finer than Sentinel-2's 10 m
WORLD = 40075016.685578488  # Web Mercator metres round the equator
MODES = {
    # Bright enough for dark forest and rock in low autumn sun; the S-curve keeps
    # texture in sunlit snow. L2A values are reflectance x 10,000 plus 1,000, and 0
    # off the swath, which the band files don't mark themselves: `nodata=0` makes it
    # transparent rather than black.
    "natural": (
        "assets=B04&assets=B03&assets=B02&rescale=1000,12000"
        "&color_formula=Gamma+RGB+2.4+Sigmoidal+RGB+4+0.3&nodata=0"
    ),
    # Shortwave infrared, near infrared, red: snow cyan, cloud white.
    "snow": (
        "assets=B11&assets=B8A&assets=B04&rescale=1000,9000&color_formula=Gamma+RGB+1.3&nodata=0"
    ),
}
# Cloud and cloud shadow (SCL 3, 8, 9, 10), and the bright cloud SCL misses (see
# sat.BRIGHT_BLUE), as 0; anything else seen as 255.
CLEAR_MASK = (
    "expression="
    + quote(
        "where((SCL_b1==3)|(SCL_b1==8)|(SCL_b1==9)|(SCL_b1==10)"
        "|((B02_b1>4000)&(B11_b1>3500)),0,255)"
    )
    + "&rescale=0,255"
)
CLOUD_MARGIN = 4  # mask pixels (20 m each) cut round cloud
# Cloud specks up to this many mask pixels across (SCL calls some bright rock and snow
# cloud) are ignored before the margin goes on: otherwise each leaves an 80 m hole.
CLOUD_SPECK = 2
QUALITY = 85

Box = tuple[float, float, float, float]  # Web Mercator: x0, y0, x1, y1


def quarters(box: Box) -> list[tuple[Box, int, int]]:
    """The four quarters of a box, with where each goes in the whole (column, row)."""
    x0, y0, x1, y1 = box
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    return [
        ((x0, my, mx, y1), 0, 0),
        ((mx, my, x1, y1), 1, 0),
        ((x0, y0, mx, my), 0, 1),
        ((mx, y0, x1, my), 1, 1),
    ]


def view_id(kind: str, box: Box, ids: Sequence[str]) -> str:
    """A view's name: changes with what it shows, the area and the drawing."""
    key = f"{RENDER}|{kind}|{','.join(f'{v:.0f}' for v in box)}|{'|'.join(ids)}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


class Renderer:
    def __init__(self, sat_dir: Path, client: httpx.Client, workers: int = 4) -> None:
        self.crops = sat_dir / "crops"
        self.views = sat_dir / "views"
        self.client = client
        self.workers = workers
        self.fetched = 0  # upstream pictures fetched (not from the cache)

    # --- pictures of passes -------------------------------------------------------

    def _get(self, url: str) -> bytes | None:
        r = self.client.get(url, timeout=90)
        if r.status_code == 404:
            return None  # the tile doesn't reach this quarter
        r.raise_for_status()
        self.fetched += 1
        return r.content

    def _quarters(self, item: str, box: Box, size: int, ext: str, query: str) -> list[bytes | None]:
        urls = [
            f"{PC_BBOX}/{q[0]:.2f},{q[1]:.2f},{q[2]:.2f},{q[3]:.2f}/{size}x{size}.{ext}"
            f"?collection=sentinel-2-l2a&item={item}&{query}"
            "&coord_crs=epsg:3857&dst_crs=epsg:3857"
            for q, _, _ in quarters(box)
        ]
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(self._get, urls))

    def _assemble(self, parts: list[bytes | None], size: int, mode: str) -> np.ndarray:
        out = Image.new(mode, (2 * size, 2 * size))
        for data, (_, col, row) in zip(parts, quarters((0, 0, 1, 1)), strict=True):
            if data is not None:
                out.paste(Image.open(io.BytesIO(data)).convert(mode), (col * size, row * size))
        return np.asarray(out)

    def picture(self, key: str, p: Pass, mode: str, box: Box) -> np.ndarray:
        """A pass's picture of the area (PX x PX RGBA, transparent where it has no data),
        from the cache or fetched."""
        path = self.crops / key / p.id / f"{mode}.webp"
        if path.exists():
            return np.asarray(Image.open(path).convert("RGBA"))
        out = np.zeros((PX, PX, 4), np.uint8)
        for it in p.items:
            a = self._assemble(self._quarters(it.id, box, HALF, "webp", MODES[mode]), HALF, "RGBA")
            take = (out[..., 3] == 0) & (a[..., 3] > 0)
            out[take] = a[take]
            if (out[..., 3] > 0).all():
                break
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(out, "RGBA").save(path, "WEBP", quality=95, method=4)
        return out

    def clear(self, key: str, p: Pass, box: Box) -> np.ndarray:
        """Where a pass saw the ground clearly, at 20 m (PX/2 square): no cloud, cloud
        shadow or no data, less CLOUD_MARGIN pixels round cloud."""
        path = self.crops / key / p.id / f"clear{CLOUD_MARGIN}s{CLOUD_SPECK}b.png"
        if path.exists():
            m = np.asarray(Image.open(path).convert("L")) > 0
        else:
            n = PX // 2
            clear = np.zeros((n, n), bool)
            cloud = np.zeros((n, n), bool)
            for it in p.items:
                a = self._assemble(
                    self._quarters(it.id, box, n // 2, "png", CLEAR_MASK), n // 2, "LA"
                )
                seen = (a[..., 1] > 0) & ~(clear | cloud)  # not decided by an earlier tile
                clear |= seen & (a[..., 0] > 0)
                cloud |= seen & (a[..., 0] == 0)
            seen = clear | cloud
            cloud = grow(~grow(~cloud, CLOUD_SPECK), CLOUD_SPECK)  # opened: specks gone
            m = seen & ~grow(cloud, CLOUD_MARGIN)
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray((m * 255).astype(np.uint8), "L").save(path, "PNG", optimize=True)
        return m

    # --- views ----------------------------------------------------------------------

    def _done(self, view: str) -> bool:
        return (self.views / view / "done").exists()

    def scene(self, key: str, p: Pass, box: Box) -> str:
        """Draw a whole pass as a view (if not drawn already); returns its name."""
        view = view_id("scene", box, [p.id])
        if not self._done(view):
            for mode in MODES:
                self.cut(self.picture(key, p, mode, box), box, self.views / view / mode)
            (self.views / view / "done").touch()
        return view

    def stitched(self, key: str, layers: Sequence[Pass], owner: np.ndarray, box: Box) -> str:
        """Draw a stitched view (see the module's notes); returns its name."""
        view = view_id(
            "stitched", box, [p.id for p in layers] + [hashlib.sha1(owner.tobytes()).hexdigest()]
        )
        if self._done(view):
            return view
        ok, seen = [], []
        for p in layers:
            has = self.picture(key, p, "natural", box)[..., 3] > 0
            seen.append(has)
            ok.append(upsample2(self.clear(key, p, box)) & has)
        choice = choose(owner, ok, seen)
        del ok, seen
        for mode in MODES:
            out = np.zeros((PX, PX, 4), np.uint8)
            for i, p in enumerate(layers):
                sel = choice == i
                if sel.any():
                    out[sel] = self.picture(key, p, mode, box)[sel]
            self.cut(out, box, self.views / view / mode)
        (self.views / view / "done").touch()
        return view

    def cut(self, rgba: np.ndarray, box: Box, out_dir: Path) -> int:
        """Cut a picture of `box` into the map's tiles for ZOOMS; returns how many."""
        x0, y0, x1, y1 = box
        res = (x1 - x0) / rgba.shape[1]
        src = Image.fromarray(rgba, "RGBA").convert("RGBa")  # premultiplied: no dark fringes
        count = 0
        for z in ZOOMS:
            span = WORLD / 2**z  # metres a tile
            tres = span / TILE
            img, r = src, res
            if tres / res > 1.25:  # shrink first, so the tile isn't sampled sparsely
                w = max(1, round(src.width * res / tres))
                img = src.resize((w, w), Image.Resampling.LANCZOS)
                r = (x1 - x0) / w
            half = WORLD / 2
            tx0, tx1 = math.floor((x0 + half) / span), math.floor((x1 + half) / span)
            ty0, ty1 = math.floor((half - y1) / span), math.floor((half - y0) / span)
            for tx in range(tx0, tx1 + 1):
                for ty in range(ty0, ty1 + 1):
                    left, top = tx * span - half, half - ty * span
                    data = (tres / r, 0, (left - x0) / r, 0, tres / r, (y1 - top) / r)
                    tile = img.transform(
                        (TILE, TILE), Image.Transform.AFFINE, data, Image.Resampling.BILINEAR
                    ).convert("RGBA")
                    if tile.getchannel("A").getbbox() is None:
                        continue  # nothing in it
                    path = out_dir / str(z) / str(tx) / f"{ty}.webp"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tile.save(path, "WEBP", quality=QUALITY, method=4)
                    count += 1
        return count

    def prune(self, views: set[str], crops: dict[str, set[str]]) -> None:
        """Delete views and pass pictures nothing uses any more."""
        if self.views.exists():
            for d in self.views.iterdir():
                if d.name not in views:
                    shutil.rmtree(d, ignore_errors=True)
        if self.crops.exists():
            for spot in self.crops.iterdir():
                keepers = crops.get(spot.name, set())
                for d in spot.iterdir():
                    if d.name not in keepers:
                        shutil.rmtree(d, ignore_errors=True)
                if not any(spot.iterdir()):
                    spot.rmdir()


def grow(m: np.ndarray, r: int) -> np.ndarray:
    """A mask grown by `r` pixels (a square window)."""
    if r <= 0:
        return m
    h, w = m.shape
    a = np.pad(m, r).astype(np.int32)
    cs = np.cumsum(np.pad(a, ((0, 0), (1, 0))), axis=1)
    rows = cs[:, 2 * r + 1 :] - cs[:, :w]
    cs = np.cumsum(np.pad(rows, ((1, 0), (0, 0))), axis=0)
    out: np.ndarray = (cs[2 * r + 1 :, :] - cs[:h, :]) > 0
    return out


def upsample2(m: np.ndarray) -> np.ndarray:
    """A 20 m mask at 10 m."""
    out: np.ndarray = np.repeat(np.repeat(m, 2, axis=0), 2, axis=1)
    return out


def choose(
    owner: np.ndarray, ok: Sequence[np.ndarray], seen: Sequence[np.ndarray] | None = None
) -> np.ndarray:
    """Which layer each pixel comes from (-1: none).

    First the layer whose part it is in (the grid's parts scaled up smoothly, so the
    joins aren't 250 m stairs), if that layer saw it clearly; then the layer nearest in
    time to that one (layers are newest first) that did, so a gap looks like its
    surroundings. Given `seen` (where each layer has data at all), what's still left (cloud in
    every layer) comes from its part's layer, else the newest with data: a pass's own
    sharp picture of the cloud beats a hole showing the 375 m mosaic."""
    size = ok[0].shape[0] if ok else PX
    choice = np.full((size, size), -1, np.int8)
    if not ok:
        return choice
    best = np.zeros((size, size), np.uint8)
    pref = np.full((size, size), -1, np.int8)
    for i in range(len(ok)):
        w = np.asarray(
            Image.fromarray(((owner == i) * 255).astype(np.uint8), "L").resize(
                (size, size), Image.Resampling.BILINEAR
            )
        )
        better = w > best
        pref[better] = i
        best = np.maximum(best, w)
    for i, m in enumerate(ok):
        choice[(pref == i) & m] = i
    n = len(ok)
    for i in range(n):
        gap = (choice < 0) & (pref == i)
        for j in sorted(range(n), key=lambda j: (abs(j - i), j)):
            if not gap.any():
                break
            take = gap & ok[j]
            choice[take] = j
            gap &= ~take
    for i, m in enumerate(ok):
        choice[(choice < 0) & m] = i
    if seen is not None:
        for i, m in enumerate(seen):
            choice[(choice < 0) & (pref == i) & m] = i
        for i, m in enumerate(seen):
            choice[(choice < 0) & m] = i
    return choice
