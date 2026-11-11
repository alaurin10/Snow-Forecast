"""NOAA GRIB2 messages fetched by HTTP byte range, decoded, and put on the region's grid.

NOAA's model files on AWS (HRRR, NBM, RRFS, MRMS) each come with a `.idx` sidecar listing
every message's byte offset, so one field costs one small range request (0.01–2 MB)
rather than the whole file. `gribberish` decodes a message and gives the latitude and
longitude of every grid point, whatever the projection, so no GDAL or pyproj is needed.

Decode one message at a time and resample it to the region straight away: a full model
grid as float64 is tens of MB.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from snowwatch.maps.files import save_npy, write_atomic
from snowwatch.maps.geomet import Net
from snowwatch.maps.region import WORLD, Region, spread

log = logging.getLogger("snowwatch.precip")


@dataclass(frozen=True)
class IdxEntry:
    """One message in a `.idx` file: its byte range and its description."""

    n: int
    start: int
    end: int | None  # inclusive; None for the file's last message
    date: str  # "d=2026111014"
    var: str  # "APCP"
    level: str  # "surface"
    fcst: str  # "0-1 hour acc fcst"
    # Anything after the forecast field: NBM's probability and percentile messages share
    # the deterministic message's name and differ only here ("prob >0.254:prob fcst 255/255").
    extra: str = ""

    @property
    def line(self) -> str:
        """The description as wgrib2 writes it, for matching: ":APCP:surface:0-1 hour acc fcst:"."""
        return f":{self.var}:{self.level}:{self.fcst}:"


def parse_idx(text: str) -> list[IdxEntry]:
    """NOAA's wgrib2 index: `n:offset:d=YYYYMMDDHH:VAR:level:forecast:` per line.

    Each message ends where the next begins. Lines that don't parse are skipped."""
    rows: list[tuple[int, int, list[str]]] = []
    for raw in text.splitlines():
        bits = raw.split(":")
        if len(bits) < 6:
            continue
        try:
            rows.append((int(bits[0]), int(bits[1]), bits))
        except ValueError:
            continue
    rows.sort(key=lambda r: r[1])
    out = []
    for i, (n, start, bits) in enumerate(rows):
        end = rows[i + 1][1] - 1 if i + 1 < len(rows) else None
        extra = ":".join(bits[6:]).strip(":")
        out.append(IdxEntry(n, start, end, bits[2], bits[3], bits[4], bits[5], extra))
    return out


def find(entries: list[IdxEntry], pattern: str) -> IdxEntry | None:
    """The first plain (not probability or percentile) message whose description matches
    a regex, such as r":APCP:surface:0-1 hour acc fcst:" (matched against `IdxEntry.line`)."""
    rx = re.compile(pattern)
    return next((e for e in entries if not e.extra and rx.search(e.line)), None)


def fetch_message(net: Net, url: str, pattern: str) -> bytes | None:
    """One message of a GRIB2 file on a web server, by its `.idx` and a range request."""
    return fetch_messages(net, url, [pattern])[0]


def _cache_path(cache_dir: Path, url: str, pattern: str) -> Path:
    return cache_dir / f"{hashlib.sha1(f'{url}|{pattern}'.encode()).hexdigest()[:20]}.grib2"


def fetch_messages(
    net: Net, url: str, patterns: list[str], cache_dir: Path | None = None
) -> list[bytes | None]:
    """Several messages of one GRIB2 file: one `.idx` request, then a range request each.

    With `cache_dir`, messages are kept on disk by URL and pattern (model files never
    change once published), so the same field isn't downloaded twice."""
    out: list[bytes | None] = [None] * len(patterns)
    todo = list(range(len(patterns)))
    if cache_dir is not None:
        for i in list(todo):
            path = _cache_path(cache_dir, url, patterns[i])
            if path.exists():
                with contextlib.suppress(OSError):
                    out[i] = path.read_bytes()
                    todo.remove(i)
                    os.utime(path)  # still in use: pruning goes by last use
    if not todo:
        return out
    r = net.get(url + ".idx")
    if r is None:
        return out
    entries = parse_idx(r.text)
    for i in todo:
        entry = find(entries, patterns[i])
        if entry is None:
            log.debug("no %s in %s", patterns[i], url)
            continue
        data = net.range(url, entry.start, entry.end)
        if data is None or not data.startswith(b"GRIB"):
            continue
        out[i] = data
        if cache_dir is not None:
            write_atomic(_cache_path(cache_dir, url, patterns[i]), data)
    return out


def prune_cache(cache_dir: Path, max_age_s: float = 86400) -> int:
    """Drop cached messages not used for `max_age_s` (their model runs have been replaced)."""
    cutoff = time.time() - max_age_s
    removed = 0
    for p in cache_dir.glob("*.grib2"):
        with contextlib.suppress(OSError):
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
    return removed


class Metadata(Protocol):
    """What we use of gribberish's message metadata."""

    @property
    def grid_shape(self) -> tuple[int, int]: ...

    @property
    def proj(self) -> str: ...

    def latlng(self) -> tuple[np.ndarray, np.ndarray]: ...


def decode(raw: bytes) -> tuple[np.ndarray, Any]:
    """A GRIB2 message to its values as float32 in grid order (rows, cols), and its metadata.

    The metadata has `var_abbrev`, `units`, `reference_date`, `forecast_date`, `grid_shape`,
    `proj` and `latlng()`. Missing values come back as NaN."""
    import gribberish  # type: ignore[import-untyped]

    msg = gribberish.parse_grib_message(raw, 0)
    md = msg.metadata
    values = np.asarray(msg.data(), dtype=np.float32).reshape(md.grid_shape)
    if scanning_mode(raw) & ALTERNATE_ROWS:
        values = unsnake(values)
    return values, md


# Scanning mode flag 0x10: "adjacent rows scan in opposite directions". NBM's grid uses it
# (mode 0x50); gribberish returns the values as read, so every other row comes out
# mirrored. (HRRR's mode is 0x40.)
ALTERNATE_ROWS = 0x10
# Where the scanning mode byte sits in section 3, by grid template (0-based from the
# section's start): lat/lon 3.0, Mercator 3.10, polar stereographic 3.20, Lambert 3.30.
_SCAN_OFFSET = {0: 71, 1: 71, 10: 59, 20: 64, 30: 64, 31: 64, 40: 71}


def scanning_mode(raw: bytes) -> int:
    """The grid's scanning mode flags from a GRIB2 message's section 3 (0 if not found)."""
    off = 16  # section 0 is 16 bytes
    while off + 5 <= len(raw):
        length = int.from_bytes(raw[off : off + 4], "big")
        number = raw[off + 4]
        if length <= 0 or number > 7:
            return 0
        if number == 3:
            template = int.from_bytes(raw[off + 12 : off + 14], "big")
            at = _SCAN_OFFSET.get(template)
            return raw[off + at] if at is not None and at < length else 0
        off += length
    return 0


def unsnake(values: np.ndarray) -> np.ndarray:
    """Undo alternating row direction: the second, fourth, … rows run backwards."""
    out = values.copy()
    out[1::2] = out[1::2, ::-1]
    return out


def _grid_key(md: Metadata, region: Region) -> str:
    lat, lon = md.latlng()
    corners = [float(a[i]) for a in (lat, lon) for i in (0, -1)]
    text = f"{md.grid_shape}|{md.proj}|{corners}|{region.key}"
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def index_map(md: Metadata, region: Region, cache_dir: Path | None = None) -> np.ndarray:
    """For each region pixel, the flat index of the nearest source grid cell (-1: none).

    Built from the grid's own latitudes and longitudes: each source cell lands in the
    pixel under it, then pixels between cells take a neighbour's cell, out to about one
    source cell's width. Computed once per model grid and region, and cached as `.npy`
    (and in memory, keyed by grid shape and projection, so a job doesn't rebuild it)."""
    memo_key = (tuple(md.grid_shape), str(md.proj), region.key)
    have = _MEMO.get(memo_key)
    if have is not None:
        return have
    out = _index_map(md, region, cache_dir)
    if len(_MEMO) >= 8:
        _MEMO.pop(next(iter(_MEMO)))
    _MEMO[memo_key] = out
    return out


_MEMO: dict[tuple[tuple[int, ...], str, str], np.ndarray] = {}


def _index_map(md: Metadata, region: Region, cache_dir: Path | None) -> np.ndarray:
    path = None
    if cache_dir is not None:
        path = cache_dir / f"{_grid_key(md, region)}.npy"
        if path.exists():
            try:
                cached: np.ndarray = np.load(path)
                if cached.shape == (region.height, region.width):
                    return cached
            except (OSError, ValueError):
                pass
    lat, lon = (np.asarray(a, dtype=np.float64).ravel() for a in md.latlng())
    lon = (lon + 180) % 360 - 180
    lat = np.clip(lat, -85, 85)
    sx = region.width / (region.x1 - region.x0)
    sy = region.height / (region.y1 - region.y0)
    x = lon * WORLD / 180
    y = np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * WORLD / np.pi
    col = np.floor((x - region.x0) * sx).astype(np.int64)
    row = np.floor((region.y1 - y) * sy).astype(np.int64)
    inside = (col >= 0) & (col < region.width) & (row >= 0) & (row < region.height)
    flat = np.full(region.height * region.width, -1, np.int32)
    flat[row[inside] * region.width + col[inside]] = np.flatnonzero(inside).astype(np.int32)
    out = flat.reshape(region.height, region.width)
    # How far apart neighbouring source cells land, in pixels: fill gaps that wide.
    rows, cols = md.grid_shape
    mid = (rows // 2) * cols + np.arange(cols)
    step = np.hypot(np.diff(col[mid]), np.diff(row[mid]))
    passes = math.ceil(float(np.median(step))) + 1 if step.size else 1
    out = spread(out, min(passes, 50), empty=-1)
    if path is not None:
        save_npy(path, out)
    return out


def resample(values: np.ndarray, imap: np.ndarray) -> np.ndarray:
    """Source values onto the region via an `index_map` (NaN where it has none)."""
    flat = values.ravel()
    out = np.full(imap.shape, np.nan, np.float32)
    have = imap >= 0
    out[have] = flat[imap[have]]
    return out


def on_region(
    raw: bytes | None, region: Region, grids_dir: Path | None = None
) -> np.ndarray | None:
    """A GRIB2 message decoded and resampled onto the region (NaN off the model's grid)."""
    if raw is None:
        return None
    try:
        values, md = decode(raw)
    except Exception as e:  # gribberish raises its own error types
        log.warning("undecodable GRIB message: %s", e)
        return None
    return resample(values, index_map(md, region, grids_dir))
