"""The box the map's pictures cover, in Web Mercator so they line up with the map."""

from __future__ import annotations

import math
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

import numpy as np

WORLD = 20037508.342789244  # half the Web Mercator world, metres
WIDTH = 1400  # frame width in pixels when the box follows the locations
MAX_HEIGHT = 2400
TILE_ZOOM = 7  # RainViewer's free tiles stop at 7; IEM's HRRR is ~3 km, so 7 is plenty

# The fixed western North America box: south, west, north, east (config: map.region).
WEST = (31.0, -134.0, 57.0, -102.0)


def merc_x(lon: float) -> float:
    return lon * WORLD / 180


def merc_y(lat: float) -> float:
    lat = max(min(lat, 85.0), -85.0)
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * WORLD / math.pi


def merc_lat(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(y * math.pi / WORLD)) - math.pi / 2)


@dataclass(frozen=True)
class Region:
    """A box in Web Mercator metres and its size in pixels."""

    x0: float
    y0: float
    x1: float
    y1: float
    width: int
    height: int

    @property
    def bounds(self) -> list[list[float]]:
        """[[south, west], [north, east]] in degrees, as Leaflet wants."""
        w, e = self.x0 * 180 / WORLD, self.x1 * 180 / WORLD
        return [
            [round(merc_lat(self.y0), 5), round(w, 5)],
            [round(merc_lat(self.y1), 5), round(e, 5)],
        ]

    @property
    def key(self) -> str:
        return f"{self.x0:.0f},{self.y0:.0f},{self.x1:.0f},{self.y1:.0f},{self.width}x{self.height}"

    def lonlats(self) -> tuple[np.ndarray, np.ndarray]:
        """Longitude of each column's centre and latitude of each row's (row 0 is north)."""
        xs = self.x0 + (np.arange(self.width) + 0.5) * (self.x1 - self.x0) / self.width
        ys = self.y1 - (np.arange(self.height) + 0.5) * (self.y1 - self.y0) / self.height
        lons = xs * 180 / WORLD
        lats = np.degrees(2 * np.arctan(np.exp(ys * math.pi / WORLD)) - math.pi / 2)
        return lons, lats


def box_region(south: float, west: float, north: float, east: float, width: int) -> Region:
    x0, x1 = merc_x(west), merc_x(east)
    y0, y1 = merc_y(south), merc_y(north)
    height = min(MAX_HEIGHT, round(width * (y1 - y0) / (x1 - x0)))
    return Region(x0, y0, x1, y1, width, height)


def region_around(points: Iterable[tuple[float, float]], width: int = WIDTH) -> Region:
    """The locations (lat, lon) with a margin: weather arrives from well upwind."""
    pts = list(points) or [(47.4, -121.4)]
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    south, north = min(lats) - 5, max(lats) + 6
    west, east = min(lons) - 10, max(lons) + 8
    # At least ~12 x 18 degrees, so a single location still gets context.
    if north - south < 12:
        mid = (north + south) / 2
        south, north = mid - 6, mid + 6
    if east - west < 18:
        mid = (east + west) / 2
        west, east = mid - 9, mid + 9
    x0, x1 = merc_x(west), merc_x(east)
    y0, y1 = merc_y(south), merc_y(north)
    height = min(1800, round(width * (y1 - y0) / (x1 - x0)))
    return Region(x0, y0, x1, y1, width, height)


def region_for(
    points: Iterable[tuple[float, float]],
    box: tuple[float, float, float, float] | None = None,
    width: int = WIDTH,
) -> Region:
    """A fixed box (south, west, north, east), widened to take in any location outside
    it with a degree to spare. Without a box, the old behaviour: follow the locations."""
    if box is None:
        return region_around(points, width)
    south, west, north, east = box
    for lat, lon in points:
        south, north = min(south, lat - 1), max(north, lat + 1)
        west, east = min(west, lon - 1), max(east, lon + 1)
    return box_region(south, west, north, east, width)


def spread(values: np.ndarray, passes: int, empty: int = 0) -> np.ndarray:
    """Fill empty cells from their neighbours, one pixel further each pass.

    A cheap nearest-neighbour fill: after `passes`, every empty cell within that many
    pixels (city-block distance) of a filled one has a nearby value."""
    out = values.copy()
    for _ in range(passes):
        hole = out == empty
        if not hole.any():
            break
        for src, dst in (
            (np.s_[:-1, :], np.s_[1:, :]),
            (np.s_[1:, :], np.s_[:-1, :]),
            (np.s_[:, :-1], np.s_[:, 1:]),
            (np.s_[:, 1:], np.s_[:, :-1]),
        ):
            take = hole[dst] & (out[src] != empty)
            out[dst][take] = out[src][take]
            hole[dst] &= ~take
    return out


# ---- XYZ tiles -------------------------------------------------------------------


class ImageGetter(Protocol):
    def image(
        self, url: str, params: dict[str, str] | None = None, tries: int = 3
    ) -> np.ndarray | None: ...


def stitch(
    net: ImageGetter, template: str, region: Region, z: int = TILE_ZOOM
) -> np.ndarray | None:
    """XYZ tiles covering the region, resampled onto its pixel grid. None if none came."""
    world_px = 256 * 2**z

    def px(x: float) -> float:
        return float((x + WORLD) / (2 * WORLD) * world_px)

    def py(y: float) -> float:
        return float((WORLD - y) / (2 * WORLD) * world_px)

    gx0, gx1 = px(region.x0), px(region.x1)
    gy0, gy1 = py(region.y1), py(region.y0)
    tx0, tx1 = int(gx0 // 256), int((gx1 - 1) // 256)
    ty0, ty1 = int(gy0 // 256), int((gy1 - 1) // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 4), np.uint8)
    coords = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]

    def one(c: tuple[int, int]) -> tuple[tuple[int, int], np.ndarray | None]:
        x, y = c
        # Tile caches serve or they don't: no retries (a missing hour can take 20 s to fail).
        return c, net.image(template.format(z=z, x=x, y=y), tries=1)

    # One tile from the middle first: if the source has nothing, don't ask for the rest.
    probe = coords[len(coords) // 2]
    if one(probe)[1] is None and one(coords[0])[1] is None:
        return None
    got = 0
    with ThreadPoolExecutor(6) as pool:
        for (x, y), img in pool.map(one, coords):
            if img is None or img.shape[:2] != (256, 256):
                continue
            got += 1
            mosaic[(y - ty0) * 256 : (y - ty0 + 1) * 256, (x - tx0) * 256 : (x - tx0 + 1) * 256] = (
                img
            )
    if not got:
        return None
    # Nearest-neighbour sample: both grids are Web Mercator, so the mapping is linear.
    cols = (gx0 + (np.arange(region.width) + 0.5) * (gx1 - gx0) / region.width - tx0 * 256).astype(
        int
    )
    rows = (
        gy0 + (np.arange(region.height) + 0.5) * (gy1 - gy0) / region.height - ty0 * 256
    ).astype(int)
    cols = np.clip(cols, 0, mosaic.shape[1] - 1)
    rows = np.clip(rows, 0, mosaic.shape[0] - 1)
    out: np.ndarray = mosaic[rows][:, cols]
    return out
