"""NOAA GRIB2 messages fetched by HTTP byte range, decoded, and put on the region's grid.

NOAA's model files on AWS (HRRR, NBM, RRFS, MRMS) each come with a `.idx` sidecar listing
every message's byte offset, so one field costs one small range request (0.01–2 MB)
rather than the whole file. `gribberish` decodes a message and gives the latitude and
longitude of every grid point, whatever the projection, so no GDAL or pyproj is needed.

Decode one message at a time and resample it to the region straight away: a full model
grid as float64 is tens of MB.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

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
        out.append(IdxEntry(n, start, end, bits[2], bits[3], bits[4], bits[5]))
    return out


def find(entries: list[IdxEntry], pattern: str) -> IdxEntry | None:
    """The first message whose description matches a regex, such as
    r":APCP:surface:0-1 hour acc fcst:" (matched against `IdxEntry.line`)."""
    rx = re.compile(pattern)
    return next((e for e in entries if rx.search(e.line)), None)


def fetch_message(net: Net, url: str, pattern: str) -> bytes | None:
    """One message of a GRIB2 file on a web server, by its `.idx` and a range request."""
    r = net.get(url + ".idx")
    if r is None:
        return None
    entry = find(parse_idx(r.text), pattern)
    if entry is None:
        log.debug("no %s in %s", pattern, url)
        return None
    data = net.range(url, entry.start, entry.end)
    if data is None or not data.startswith(b"GRIB"):
        return None
    return data


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
    return values, md


def _grid_key(md: Metadata, region: Region) -> str:
    lat, lon = md.latlng()
    corners = [float(a[i]) for a in (lat, lon) for i in (0, -1)]
    text = f"{md.grid_shape}|{md.proj}|{corners}|{region.key}"
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def index_map(md: Metadata, region: Region, cache_dir: Path | None = None) -> np.ndarray:
    """For each region pixel, the flat index of the nearest source grid cell (-1: none).

    Built from the grid's own latitudes and longitudes: each source cell lands in the
    pixel under it, then pixels between cells take a neighbour's cell, out to about one
    source cell's width. Computed once per model grid and region, and cached as `.npy`."""
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
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.npy")
        np.save(tmp, out)
        tmp.replace(path)
    return out


def resample(values: np.ndarray, imap: np.ndarray) -> np.ndarray:
    """Source values onto the region via an `index_map` (NaN where it has none)."""
    flat = values.ravel()
    out = np.full(imap.shape, np.nan, np.float32)
    have = imap >= 0
    out[have] = flat[imap[have]]
    return out
