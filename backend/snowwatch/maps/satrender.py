"""Drawing the map's recent satellite views (docs/MAP-PLAN.md, B6).

Every view is drawn once, by the worker, as one picture of its `Area` in Web Mercator,
then cut into the map's 512 px tiles under `data/sat/views/<view>/<natural|snow>/`. The
browser then loads one layer of small finished tiles: nothing is fetched or drawn
upstream while it pans. Two areas round each location:

- `CENTRE`: 24 x 24 km at Sentinel-2's own 10 m (2,400 pixels a side), zooms 9-13.
- `WIDE`: the ring round it, 72 x 72 km at 30 m (also 2,400 pixels, so it costs about
  as much to draw as the centre), zooms 7-12. Only a stitched view; the centre is drawn
  over its middle.

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
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx
import numpy as np
from PIL import Image, ImageFilter

if TYPE_CHECKING:
    from snowwatch.maps.sat import Pass

log = logging.getLogger("snowwatch.sat")

PC_BBOX = "https://planetarycomputer.microsoft.com/api/data/v1/item/bbox"
# Bumped whenever the drawing changes, so every view is drawn afresh (new names).
RENDER = 6
TILE = 512
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
QUALITY = 85
# A pass's mask (see Renderer.mask): no data, cloud or its shadow, clear.
M_NODATA, M_CLOUD, M_CLEAR = 0, 1, 2
# Stitched views: parts' borders are curved over about this much ground, and joins
# between passes fade over about this much (less than the cloud margin, so a fade never
# reaches into cloud).
PART_SOFTEN_M = 120
FEATHER_M = 50


@dataclass(frozen=True)
class Area:
    """The square drawn round a location, and how."""

    name: str  # goes into its stitched views' names ("stitched" at the centre, as before)
    km: float  # half its width on the ground
    px: int  # pixels a side of its picture; the cloud mask is half that
    zooms: range  # of its tiles
    # Mask pixels cut round cloud, and cloud specks up to this many mask pixels across
    # (SCL calls some bright rock and snow cloud) ignored before the margin goes on, so
    # each doesn't leave a hole: 80 m and 40 m at the centre's 20 m mask.
    cloud_margin: int
    cloud_speck: int
    max_layers: int  # passes in a stitched view at most

    @property
    def half(self) -> int:
        return self.px // 2


# Zoom 13 is ~6.5 m a pixel here, finer than Sentinel-2's 10 m; zoom 12 ~13 m, about
# the wide picture's 30 m at its sharpest.
CENTRE = Area("stitched", 12.0, 2400, range(9, 14), 4, 2, 6)
WIDE = Area("wide", 36.0, 2400, range(7, 13), 2, 1, 8)

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

    def picture(self, key: str, p: Pass, mode: str, box: Box, area: Area) -> np.ndarray:
        """A pass's picture of the area (px x px RGBA, transparent where it has no data),
        from the cache or fetched."""
        path = self.crops / key / p.id / f"{mode}.webp"
        if path.exists():
            return np.asarray(Image.open(path).convert("RGBA"))
        out = np.zeros((area.px, area.px, 4), np.uint8)
        for it in p.items:
            a = self._assemble(
                self._quarters(it.id, box, area.half, "webp", MODES[mode]), area.half, "RGBA"
            )
            take = (out[..., 3] == 0) & (a[..., 3] > 0)
            out[take] = a[take]
            if (out[..., 3] > 0).all():
                break
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(out, "RGBA").save(path, "WEBP", quality=95, method=4)
        return out

    def mask(self, key: str, p: Pass, box: Box, area: Area) -> np.ndarray:
        """What a pass saw, at half the picture's size (20 m at the centre): M_NODATA,
        M_CLOUD (cloud or its shadow) or M_CLEAR, from the cache or fetched. Kept as it
        came, so changing how it is cleaned up (`clear`) fetches nothing."""
        path = self.crops / key / p.id / "mask.png"
        if path.exists():
            return np.asarray(Image.open(path).convert("L"))
        n = area.half
        out = np.zeros((n, n), np.uint8)
        for it in p.items:
            a = self._assemble(self._quarters(it.id, box, n // 2, "png", CLEAR_MASK), n // 2, "LA")
            new = (a[..., 1] > 0) & (out == M_NODATA)  # not decided by an earlier tile
            out[new & (a[..., 0] > 0)] = M_CLEAR
            out[new & (a[..., 0] == 0)] = M_CLOUD
            if (out != M_NODATA).all():
                break
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(out, "L").save(path, "PNG", optimize=True)
        for old in path.parent.glob("clear*.png"):  # the cleaned-up masks kept before
            old.unlink(missing_ok=True)
        return out

    def clear(self, key: str, p: Pass, box: Box, area: Area) -> np.ndarray:
        """Where a pass saw the ground clearly, at half the picture's size: seen and not
        cloud, less a margin round cloud (specks of "cloud" first left out: SCL calls some
        bright rock and snow cloud). Both are grown roughly round, so the holes they leave
        are blobs, not boxes."""
        m = self.mask(key, p, box, area)
        speck = area.cloud_speck
        cloud = grow(~grow(m != M_CLOUD, speck), speck)  # opened: specks gone
        out: np.ndarray = (m != M_NODATA) & ~grow(cloud, area.cloud_margin)
        return out

    # --- views ----------------------------------------------------------------------

    def _done(self, view: str) -> bool:
        return (self.views / view / "done").exists()

    def scene(self, key: str, p: Pass, box: Box, area: Area) -> str:
        """Draw a whole pass as a view (if not drawn already); returns its name."""
        view = view_id("scene", box, [p.id])
        if not self._done(view):
            for mode in MODES:
                self.cut(
                    self.picture(key, p, mode, box, area), box, self.views / view / mode, area.zooms
                )
            (self.views / view / "done").touch()
        return view

    def stitched(
        self, key: str, layers: Sequence[Pass], owner: np.ndarray, box: Box, area: Area
    ) -> str:
        """Draw a stitched view (see the module's notes); returns its name."""
        view = view_id(
            area.name, box, [p.id for p in layers] + [hashlib.sha1(owner.tobytes()).hexdigest()]
        )
        if self._done(view):
            return view
        ok, seen = [], []
        for p in layers:
            has = self.picture(key, p, "natural", box, area)[..., 3] > 0
            seen.append(has)
            ok.append(upsample2(self.clear(key, p, box, area)) & has)
        res = (box[2] - box[0]) / area.px
        choice = choose(owner, ok, seen, area.px, round(PART_SOFTEN_M / res))
        del seen
        weights = feather_weights(choice, ok, max(1, round(FEATHER_M / res)))
        del ok
        for mode in MODES:
            pictures = (
                self.picture(key, p, mode, box, area) if w is not None else None
                for p, w in zip(layers, weights, strict=True)
            )
            out = blend(pictures, weights, area.px)
            self.cut(out, box, self.views / view / mode, area.zooms)
        (self.views / view / "done").touch()
        return view

    def cut(self, rgba: np.ndarray, box: Box, out_dir: Path, zooms: range) -> int:
        """Cut a picture of `box` into the map's tiles for `zooms`; returns how many."""
        x0, y0, x1, y1 = box
        res = (x1 - x0) / rgba.shape[1]
        src = Image.fromarray(rgba, "RGBA").convert("RGBa")  # premultiplied: no dark fringes
        count = 0
        for z in zooms:
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
    """A mask grown by `r` pixels, roughly round: the steps alternate a 3 x 3 square and
    a plus, so a dot grows into an octagon rather than a box."""
    out = m.copy()
    for step in range(max(0, r)):
        p = np.pad(out, 1)
        nxt = out | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
        if step % 2 == 0:
            nxt |= p[:-2, :-2] | p[:-2, 2:] | p[2:, :-2] | p[2:, 2:]
        out = nxt
    return out


def blur(m: np.ndarray, radius: float) -> np.ndarray:
    """A 0/1 (or 0-255) mask blurred, as 0-255."""
    a = m.astype(np.uint8) * (255 if m.dtype == bool else 1)
    if radius <= 0:
        return a
    out: np.ndarray = np.asarray(Image.fromarray(a, "L").filter(ImageFilter.GaussianBlur(radius)))
    return out


def feather_weights(
    choice: np.ndarray, ok: Sequence[np.ndarray], radius: int
) -> list[np.ndarray | None]:
    """How much of each layer goes into each pixel (0-255), so joins between passes fade
    over about `radius` pixels instead of being cut sharp. A layer reaches past its own
    pixels only where it saw the ground clearly, so the fade never brings in its cloud;
    inside a cloud gap there is only the pass that fills it (the gap's margin is wider
    than the fade)."""
    out: list[np.ndarray | None] = []
    for i, m in enumerate(ok):
        sel = choice == i
        if not sel.any():
            out.append(None)
            continue
        w = blur(sel, radius / 2)  # Gaussian: about all of it within twice the radius
        out.append(np.where(sel | m, w, 0).astype(np.uint8))
    return out


def blend(
    pictures: Iterable[np.ndarray | None], weights: Sequence[np.ndarray | None], size: int
) -> np.ndarray:
    """The layers' pictures (RGBA, given one at a time so only one is in memory) mixed by
    `weights` (see `feather_weights`), opaque wherever any of them has data."""
    acc = np.zeros((size, size, 3), np.uint32)
    tot = np.zeros((size, size), np.uint32)
    for pic, w in zip(pictures, weights, strict=True):
        if w is None or pic is None:
            continue
        for r0 in range(0, size, 256):  # in strips, to keep the products small
            rows = slice(r0, min(size, r0 + 256))
            ww = w[rows].astype(np.uint32) * (pic[rows, :, 3] > 0)
            acc[rows] += pic[rows, :, :3].astype(np.uint32) * ww[..., None]
            tot[rows] += ww
    out = np.zeros((size, size, 4), np.uint8)
    out[..., :3] = (acc // np.maximum(tot, 1)[..., None]).astype(np.uint8)
    out[..., 3] = np.where(tot > 0, 255, 0)
    return out


def upsample2(m: np.ndarray) -> np.ndarray:
    """A 20 m mask at 10 m."""
    out: np.ndarray = np.repeat(np.repeat(m, 2, axis=0), 2, axis=1)
    return out


def choose(
    owner: np.ndarray,
    ok: Sequence[np.ndarray],
    seen: Sequence[np.ndarray] | None = None,
    px: int = CENTRE.px,
    soften: int = 0,
) -> np.ndarray:
    """Which layer each pixel comes from (-1: none).

    First the layer whose part it is in, if that layer saw it clearly. The grid's parts
    are scaled up and blurred by `soften` pixels before the parts are drawn, so their
    borders curve with the ground rather than follow the 250 m cells.

    Then each part's cloud gaps are filled from as few other passes as can be: the one
    nearest in time (layers are newest first) that saw at least half of what the best
    one did, for all of the part's gaps at once, then the next for what's left. So a
    part's gaps all look alike instead of a scatter of passes, and alike its own ground.

    Given `seen` (where each layer has data at all), what's still left (cloud in every
    layer) comes from its part's layer, else the newest with data: a pass's own sharp
    picture of the cloud beats a hole showing the 375 m mosaic."""
    size = ok[0].shape[0] if ok else px
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
        w = blur(w, soften)
        better = w > best
        pref[better] = i
        best = np.maximum(best, w)
    for i, m in enumerate(ok):
        choice[(pref == i) & m] = i
    n = len(ok)
    for i in range(n):
        gap = (choice < 0) & (pref == i)
        while gap.any():
            seen_by = [int((gap & ok[j]).sum()) if j != i else 0 for j in range(n)]
            top = max(seen_by)
            if top == 0:
                break
            j = next(
                j for j in sorted(range(n), key=lambda j: (abs(j - i), j)) if seen_by[j] * 2 >= top
            )
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
