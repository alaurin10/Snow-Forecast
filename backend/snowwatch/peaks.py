"""Named peaks anywhere, for naming a spot (snowwatch/spots.py) after the terrain: read
from the same label tiles the map draws peak names from (OpenFreeMap's OpenMapTiles
vector tiles, layer `mountain_peak`), through the server's tile cache (snowwatch/tiles.py),
so every peak in the US and Canada is covered, not only those round saved locations.

Mapbox Vector Tiles are protocol buffers; this reads only what it needs (a layer's
features, their tags and point geometry), with no extra dependency.
"""

from __future__ import annotations

import gzip
import math
from collections.abc import Callable, Iterator
from typing import Any

ZOOM = 12  # tiles about 6–7 km across at these latitudes; every named peak is in them
LAYER = "mountain_peak"
CLASSES = {"peak", "volcano"}

Peak = tuple[str, float, float]  # name, lat, lon
GetTile = Callable[[int, int, int], bytes | None]


# --- protocol buffers, just enough ----------------------------------------------------------


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    out = shift = 0
    while True:
        b = buf[i]
        i += 1
        out |= (b & 0x7F) << shift
        if b < 0x80:
            return out, i
        shift += 7


def _fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    """(field number, wire type, value) for each field: ints for varints, bytes for
    length-delimited fields, raw bytes for fixed-size ones."""
    i, n = 0, len(buf)
    while i < n:
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            v, i = _varint(buf, i)
            yield field, wire, v
        elif wire == 2:
            size, i = _varint(buf, i)
            yield field, wire, buf[i : i + size]
            i += size
        elif wire == 1:
            yield field, wire, buf[i : i + 8]
            i += 8
        elif wire == 5:
            yield field, wire, buf[i : i + 4]
            i += 4
        else:
            raise ValueError(f"unsupported wire type {wire}")


def _packed(buf: bytes) -> list[int]:
    out, i = [], 0
    while i < len(buf):
        v, i = _varint(buf, i)
        out.append(v)
    return out


def _zigzag(v: int) -> int:
    return (v >> 1) ^ -(v & 1)


def _value(buf: bytes) -> Any:
    import struct

    for field, _, v in _fields(buf):
        if field == 1:
            return v.decode("utf-8", "replace")
        if field == 2:
            return struct.unpack("<f", v)[0]
        if field == 3:
            return struct.unpack("<d", v)[0]
        if field in (4, 5):
            return v
        if field == 6:
            return _zigzag(v)
        if field == 7:
            return bool(v)
    return None


def layer_points(data: bytes, layer: str) -> list[tuple[dict[str, Any], float, float]]:
    """Each point feature of one layer of a vector tile: (properties, x, y), with x and y
    as fractions of the tile (0–1 from its west and north edges)."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    out: list[tuple[dict[str, Any], float, float]] = []
    for field, _, raw in _fields(data):
        if field != 3:
            continue
        name, extent = None, 4096
        keys: list[str] = []
        values: list[Any] = []
        features: list[bytes] = []
        for f, _, v in _fields(raw):
            if f == 1:
                name = v.decode()
            elif f == 2:
                features.append(v)
            elif f == 3:
                keys.append(v.decode())
            elif f == 4:
                values.append(_value(v))
            elif f == 5:
                extent = v
        if name != layer:
            continue
        for feat in features:
            tags: list[int] = []
            geom: list[int] = []
            kind = 0
            for f, _, v in _fields(feat):
                if f == 2:
                    tags = _packed(v)
                elif f == 3:
                    kind = v
                elif f == 4:
                    geom = _packed(v)
            if kind != 1 or len(geom) < 3 or geom[0] & 7 != 1:  # a point: MoveTo, x, y
                continue
            props = {
                keys[tags[k]]: values[tags[k + 1]]
                for k in range(0, len(tags) - 1, 2)
                if tags[k] < len(keys) and tags[k + 1] < len(values)
            }
            out.append((props, _zigzag(geom[1]) / extent, _zigzag(geom[2]) / extent))
    return out


# --- peaks ---------------------------------------------------------------------------------


def tile_of(lat: float, lon: float, z: int = ZOOM) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def _lonlat(z: int, tx: int, ty: int, fx: float, fy: float) -> tuple[float, float]:
    n = 2**z
    lon = (tx + fx) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + fy) / n))))
    return lat, lon


def peaks_near(get_tile: GetTile, lat: float, lon: float, *, z: int = ZOOM) -> list[Peak]:
    """Every named peak in the tile holding the point and the eight around it (at least
    ~6 km in every direction), from the label tiles. Tiles that can't be had are left
    out."""
    cx, cy = tile_of(lat, lon, z)
    n = 2**z
    out: list[Peak] = []
    for ty in (cy - 1, cy, cy + 1):
        for tx in (cx - 1, cx, cx + 1):
            if not (0 <= ty < n):
                continue
            data = get_tile(z, tx % n, ty)
            if not data:
                continue
            try:
                points = layer_points(data, LAYER)
            except (ValueError, IndexError, OSError):
                continue
            for props, fx, fy in points:
                name = props.get("name")
                if not name or props.get("class") not in CLASSES:
                    continue
                p_lat, p_lon = _lonlat(z, tx, ty, fx, fy)
                out.append((str(name), p_lat, p_lon))
    return out
