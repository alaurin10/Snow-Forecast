"""Forecast clouds with their heights, as numbers for the map to draw on the terrain.

Each forecast cloud frame (layers.py) gets a numbers file beside its picture. Zoomed in,
the map holds every pixel's own elevation against the cloud there: ground inside the
cloud is drawn as fog, ground above the cloud's top is clear (a summit above a sea of
cloud), and ground beneath its base lightly shaded.

Where the heights come from (NBM, the US and Canada to about 55°N; sources/nbm.py):

- to 36 h, NBM's cloud layers. The lowest layer whose base is below LOW_MAX_M is the
  one the terrain can reach; a layer starting within MERGE_M of its top joins it. Every
  other layer, and the high cloud layer, counts as cloud above.
- to 84 h, only the lowest cloud's base: the cloud is taken to reach up from there with
  the frame's total cover, its top unknown.
- elsewhere and beyond: no heights, and the map draws the total cover as it always has.

NBM's heights are above its own ground; adding the ground (ground.py) gives heights above
sea level.

The file is one gzip stream (like dataframe.py's) of a 16-byte header and byte planes at
a quarter of the region's resolution (~5.6 km over the West box, about two NBM cells:
clouds have no finer detail worth the bytes), each row stored as differences from the
row above:

    b"SWC1"  u16 width  u16 height  u8 flags  u8 metres per height step / 10
    u16 region pixels per plane pixel  4 bytes spare               (little-endian)

    flags: 1 the heights planes follow; 2 the cloud tops are known

    cover     the frame's total cover, 0..250 (0.4% a code, in 2% steps)
    (with heights)
    known     255 where the heights apply, 0 where they don't (the map draws the cover)
    low       the low cloud's cover, likewise
    base      the low cloud's base, metres above sea level / step (0..255)
    top       its top, likewise (only when the tops are known)
    above     the cover of the cloud above it, likewise

Where there is no low cloud (or no heights) its base and top are filled in from the
nearest that has one, so the map can interpolate between pixels without a jump.
"""

from __future__ import annotations

import gzip
import struct
from dataclasses import dataclass

import numpy as np

from snowwatch.maps.region import spread
from snowwatch.maps.sources.nbm import NO_BASE_M, NO_TOP_M, CloudLayer

MAGIC = b"SWC1"
EXT = "bin"
HEADER = struct.Struct("<4sHHBBH4x")
HAS_HEIGHTS = 1
HAS_TOPS = 2
STEP_M = 30  # 0..255 steps: sea level to 7,650 m
COVER_SCALE = 2.5  # % → code
COVER_STEP = 2.0  # % (finer costs bytes and shows no difference)
DS = 4  # region pixels per plane pixel
LOW_MAX_M = 6000.0  # a layer based higher than this (above sea level) is "above"
MERGE_M = 400.0  # a layer starting this close above the low cloud's top joins it
MIN_COVER = 5.0  # %: less is no layer
DEFAULT_BASE_M = 3000.0  # filled in where no cloud is near
FILL_PASSES = 12  # how far (plane pixels) a base and top spread into clear sky


@dataclass
class Heights:
    """The low cloud and the cloud above it, on the region (NaN where unknown)."""

    low: np.ndarray  # cover %, 0 where there is no low cloud
    base: np.ndarray  # metres above sea level, NaN where no low cloud
    top: np.ndarray | None  # likewise; None: tops unknown
    above: np.ndarray  # cover % of the cloud above the low cloud
    known: np.ndarray  # bool: the heights apply here


def _combine(covers: list[np.ndarray]) -> np.ndarray:
    """Independent layers' covers (%) as one."""
    clear = np.ones_like(covers[0]) if covers else np.ones((1, 1), np.float32)
    for c in covers:
        clear = clear * (1 - np.clip(np.nan_to_num(c, nan=0.0), 0, 100) / 100)
    out: np.ndarray = (100 * (1 - clear)).astype(np.float32)
    return out


def from_layers(layers: list[CloudLayer], high: np.ndarray | None, ground: np.ndarray) -> Heights:
    """Heights from NBM's cloud layers (lowest first) and its high cloud's cover."""
    shape = ground.shape
    known = np.isfinite(layers[0].base) & np.isfinite(ground)
    low = np.zeros(shape, np.float32)
    base = np.full(shape, np.nan, np.float32)
    top = np.full(shape, np.nan, np.float32)
    taken = np.zeros((len(layers), *shape), bool)
    valid = []
    for lay in layers:
        b = np.nan_to_num(lay.base, nan=np.inf)
        c = np.nan_to_num(lay.cover, nan=0.0)
        valid.append((b < NO_BASE_M) & (c >= MIN_COVER))
    # The lowest layer the terrain can reach.
    for i, lay in enumerate(layers):
        b = lay.base + ground
        t = np.where(np.nan_to_num(lay.top, nan=np.inf) < NO_TOP_M, lay.top + ground, np.nan)
        t = np.where(np.isfinite(t), np.maximum(t, b), b + 1000)  # a top NBM didn't give
        take = valid[i] & (b < LOW_MAX_M) & ~np.isfinite(base)
        base = np.where(take, b, base)
        top = np.where(take, t, top)
        low = np.where(take, lay.cover, low)
        taken[i] |= take
    # A layer starting just above it joins it.
    for i, lay in enumerate(layers):
        b = lay.base + ground
        t = np.where(np.nan_to_num(lay.top, nan=np.inf) < NO_TOP_M, lay.top + ground, b + 1000)
        join = valid[i] & ~taken[i] & np.isfinite(base) & (b <= top + MERGE_M) & (b >= base)
        top = np.where(join, np.maximum(top, t), top)
        low = np.where(join, np.maximum(low, lay.cover), low)
        taken[i] |= join
    rest = [np.where(valid[i] & ~taken[i], lay.cover, 0.0) for i, lay in enumerate(layers)]
    if high is not None:
        rest.append(np.nan_to_num(high, nan=0.0))
    above = _combine(rest)
    return Heights(
        np.where(known, np.nan_to_num(low), 0).astype(np.float32),
        np.where(known, base, np.nan),
        np.where(known, top, np.nan),
        np.where(known, above, 0).astype(np.float32),
        known,
    )


def from_base(base_agl: np.ndarray, cover: np.ndarray, ground: np.ndarray) -> Heights:
    """Heights from the lowest cloud's base alone: cloud from there up, its top unknown,
    with the frame's total cover; no base (clear, or only cloud too high to say): the
    cover counts as cloud above."""
    known = np.isfinite(base_agl) & np.isfinite(ground)
    b = base_agl + ground
    has = known & (np.nan_to_num(base_agl, nan=np.inf) < NO_BASE_M) & (b < LOW_MAX_M)
    c = np.clip(np.nan_to_num(cover, nan=0.0), 0, 100).astype(np.float32)
    return Heights(
        np.where(has, c, 0).astype(np.float32),
        np.where(has, b, np.nan).astype(np.float32),
        None,
        np.where(known & ~has, c, 0).astype(np.float32),
        known,
    )


def _shrink(a: np.ndarray, k: int = DS) -> np.ndarray:
    """1/k the size by k × k means (NaN-aware: a block with any value keeps their mean);
    a last part-block is left out."""
    h, w = a.shape[0] // k * k, a.shape[1] // k * k
    blocks = a[:h, :w].reshape(h // k, k, w // k, k).astype(np.float32)
    have = np.isfinite(blocks)
    n = have.sum((1, 3))
    s = np.where(have, blocks, 0).sum((1, 3))
    out: np.ndarray = np.where(n > 0, s / np.maximum(n, 1), np.nan).astype(np.float32)
    return out


def _fill(a: np.ndarray) -> np.ndarray:
    """NaNs take the nearest value (out to FILL_PASSES), then DEFAULT_BASE_M."""
    sentinel = -1.0
    out = spread(np.where(np.isfinite(a), a, sentinel).astype(np.float32), FILL_PASSES, sentinel)
    out[out == sentinel] = DEFAULT_BASE_M
    return out


def _heights_code(m: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(m / STEP_M), 0, 255).astype(np.uint8)


def _cover_code(c: np.ndarray) -> np.ndarray:
    pct = np.rint(np.clip(np.nan_to_num(c, nan=0.0), 0, 100) / COVER_STEP) * COVER_STEP
    out: np.ndarray = np.rint(pct * COVER_SCALE).astype(np.uint8)
    return out


def _filtered(plane: np.ndarray) -> bytes:
    """Each row as differences from the row above (mod 256)."""
    p = plane.astype(np.int16)
    d = p.copy()
    d[1:] = p[1:] - p[:-1]
    return (d & 255).astype(np.uint8).tobytes()


def encode(cover: np.ndarray, heights: Heights | None) -> bytes:
    """A forecast cloud frame's numbers (see the module's notes), at 1/DS the size."""
    c = _shrink(np.nan_to_num(cover, nan=0.0))
    h, w = c.shape
    planes = [_cover_code(c)]
    flags = 0
    if heights is not None:
        flags |= HAS_HEIGHTS
        known = _shrink(heights.known.astype(np.float32))
        planes.append(np.clip(np.rint(known * 255), 0, 255).astype(np.uint8))
        planes.append(_cover_code(_shrink(heights.low)))
        planes.append(_heights_code(_fill(_shrink(heights.base))))
        if heights.top is not None:
            flags |= HAS_TOPS
            planes.append(_heights_code(_fill(_shrink(heights.top))))
        planes.append(_cover_code(_shrink(heights.above)))
    head = HEADER.pack(MAGIC, w, h, flags, STEP_M // 10, DS)
    body = head + b"".join(_filtered(p) for p in planes)
    return gzip.compress(body, compresslevel=6, mtime=0)


def decode(data: bytes) -> dict[str, np.ndarray | int]:
    """The planes back (for tests and tap-for-numbers): cover, and with heights known,
    low, base, top (if known) and above, in % and metres."""
    raw = gzip.decompress(data)
    magic, w, h, flags, step_dm, ds = HEADER.unpack_from(raw)
    if magic != MAGIC:
        raise ValueError("not a cloud frame")
    names = ["cover"]
    if flags & HAS_HEIGHTS:
        names += ["known", "low", "base"]
        if flags & HAS_TOPS:
            names.append("top")
        names.append("above")
    out: dict[str, np.ndarray | int] = {"flags": flags, "ds": ds}
    off = HEADER.size
    for name in names:
        d = np.frombuffer(raw, np.uint8, w * h, off).reshape(h, w).astype(np.int32)
        off += w * h
        codes = (np.cumsum(d, axis=0) & 255).astype(np.float32)
        scale = {"cover": 1 / COVER_SCALE, "low": 1 / COVER_SCALE, "above": 1 / COVER_SCALE}
        scale |= {"base": step_dm * 10.0, "top": step_dm * 10.0, "known": 1 / 255}
        out[name] = (codes * scale[name]).astype(np.float32)
    return out
