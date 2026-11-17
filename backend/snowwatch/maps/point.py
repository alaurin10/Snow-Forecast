"""Tap anywhere for numbers (docs/MAP-PLAN.md A6): what the map's pictures say at a point.

Read straight from what the worker already wrote, nothing fetched: the index
(`data/precip/index.json`), each picture's probe (every 4th pixel each way, ~6 km, see
render.py) and the snow totals as numbers (`data/maps/totals/<window>h.npy`, every pixel).

- the precipitation timeline as a typed rate band per frame (palette index → type and the
  band's bounds in mm of water an hour), from radar through the forecast; outside the box,
  radar and the nowcast from the wide loop (`data/precip/wide/`, docs/RADAR-PLAN.md M6);
- snow totals per window, and per elevation from the terrain-adjusted grids
  (`data/maps/totals/bins-<id>.npy`, see bins.py), snow level, gusts and the ridge-level
  wind with its direction through the forecast, snow on the ground, and observed snowfall;
- loading roses for the next 24 and 72 hours, as a location's snapshot has them: the
  ridge wind's direction weighted by the snow falling at the time and that wind's speed,
  for the map's wind-effect layer where no saved location is near.
"""

from __future__ import annotations

import contextlib
import json
import math
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel

from snowwatch.analysis.backcountry import BackcountryConfig, loading_rose
from snowwatch.doc import RoseOut
from snowwatch.maps import bins
from snowwatch.maps.palette import FINE, FINE_KIND, FINE_VALUE, NONE, RATE_BANDS, rate_band
from snowwatch.maps.region import merc_x, merc_y

HOUR = 3600
# Every 4th pixel each way (~4 km over the West box) by default; render.py writes them. A
# probe's own step is read from its shape (the wide loop keeps every pixel).
PROBE_STEP = 4
KIND_NAMES: dict[int, Literal["snow", "mix", "rain"]] = {1: "snow", 2: "mix", 3: "rain"}
ROSE_WINDOWS = (("next24", 24), ("next72", 72))
RIDGE_NEAR_S = 3 * HOUR  # a precipitation frame takes the ridge wind this close in time


class PointRate(BaseModel):
    """One frame of the precipitation timeline at the point."""

    t: int
    kind: str  # radar | nowcast | forecast
    span_h: int
    type: Literal["snow", "mix", "rain"] | None  # None: dry
    low: float | None  # the colour band's bounds, mm of water an hour (≈ cm of snow)
    high: float | None  # None for the top band
    # No radar sees the spot well (a blind valley, beyond range): the forecast fills in
    # (render.py, `fill_gaps`).
    filled: bool = False


class PointValue(BaseModel):
    t: int
    value: float | None


class PointWind(BaseModel):
    t: int
    kmh: float | None
    dir: float | None  # where the wind blows from, degrees


class PointTotal(BaseModel):
    window: int
    hours: int
    start: int
    end: int
    cm: float | None
    source: str
    # Snow (cm) at each of PointOut.elevations, from the terrain-adjusted grid (None
    # without one).
    by_elevation: list[float] | None = None


class PointObserved(BaseModel):
    hours: int
    end: int
    cm: float | None


class PointDepth(BaseModel):
    t: int
    cm: float | None
    src: dict[str, str]


class PointOut(BaseModel):
    """What the map's weather says at a point (GET /api/map/point)."""

    lat: float
    lon: float
    inside: bool  # within the box the pictures cover
    # Outside it but within the wide radar loop: `rates` holds its radar and nowcast only.
    wide: bool = False
    generated: str | None
    totals: list[PointTotal]
    rates: list[PointRate]
    snow_level: list[PointValue]  # metres above sea level
    gust: list[PointValue]  # km/h
    ridge: list[PointWind]
    depth: PointDepth | None
    observed: list[PointObserved]
    roses: list[RoseOut]
    min_snow_cm: float
    min_wind_kmh: float
    # The elevations (m) PointTotal.by_elevation is given at: every 250 m from 0.
    elevations: list[int] = []


def pixel(index: dict[str, Any], lat: float, lon: float) -> tuple[int, int] | None:
    """The point's row and column in the pictures, or None outside them."""
    try:
        (south, west), (north, east) = index["bounds"]
        width, height = int(index["width"]), int(index["height"])
    except (KeyError, TypeError, ValueError):
        return None
    x0, x1, y0, y1 = merc_x(west), merc_x(east), merc_y(south), merc_y(north)
    col = math.floor((merc_x(lon) - x0) / (x1 - x0) * width)
    row = math.floor((y1 - merc_y(lat)) / (y1 - y0) * height)
    if not (0 <= row < height and 0 <= col < width):
        return None
    return row, col


class Probes:
    """Reads one cell from each picture's probe (memory-mapped, so only that cell)."""

    def __init__(self, folder: Path, row: int, col: int, height: int = 0) -> None:
        self.folder = folder / "probe"
        self.row = row
        self.col = col
        self.height = height

    def cell(self, file: str) -> np.ndarray | None:
        """The probe's value(s) at the point: one per channel."""
        try:
            arr = np.load(self.folder / f"{file}.npy", mmap_mode="r")
        except (OSError, ValueError):
            return None
        # The step it was written at, from its size (a picture's rows / the probe's).
        step = max(1, round(self.height / arr.shape[-2])) if self.height else PROBE_STEP
        r = min(self.row // step, arr.shape[-2] - 1)
        c = min(self.col // step, arr.shape[-1] - 1)
        return np.atleast_1d(np.asarray(arr[..., r, c], dtype=np.float32))


def _num(v: float | None, digits: int = 1) -> float | None:
    if v is None or not math.isfinite(v):
        return None
    return round(float(v), digits)


def read_index(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _rates(index: dict[str, Any], probes: Probes) -> list[PointRate]:
    """Each frame as it is drawn: the nowcast's frames already carry their hand-over to
    the forecast (render.hand_over), so a tap reads what the map shows."""
    out: list[PointRate] = []
    timeline = sorted(index.get("frames", []), key=lambda f: f.get("valid") or f.get("t", 0))
    for f in timeline:
        kind = f.get("kind") or ("radar" if f.get("past") else "forecast")
        span = int(f.get("span_h", 1 if kind == "forecast" else 0))
        cell = probes.cell(str(f.get("file", "")))
        if cell is None:
            continue
        if f.get("palette") == FINE:
            i = int(cell[0])
            code = int(FINE_KIND[i])
            band = rate_band(code, float(FINE_VALUE[i])) if code != NONE else None
        else:
            band = RATE_BANDS.get(int(cell[0]))
        # A second channel: the share of the frame's water the forecast filled in (0..255).
        filled = band is not None and cell.size > 1 and float(cell[1]) >= 128
        if band is None:
            out.append(PointRate(t=f["t"], kind=kind, span_h=span, type=None, low=None, high=None))
        else:
            code, low, high = band
            out.append(
                PointRate(
                    t=f["t"],
                    kind=kind,
                    span_h=span,
                    type=KIND_NAMES[code],
                    low=low,
                    high=_num(high, 2),
                    filled=filled,
                )
            )
    return out


def probe(
    index: dict[str, Any],
    precip_dir: Path,
    totals_dir: Path,
    lat: float,
    lon: float,
    now: float,
    bc: BackcountryConfig,
    wide: tuple[dict[str, Any], Path] | None = None,
) -> PointOut:
    """Everything the map knows at a point. `wide` is the wide radar loop's index and
    folder, read for a point outside the box."""
    out = PointOut(
        lat=lat,
        lon=lon,
        inside=False,
        generated=index.get("generated"),
        totals=[],
        rates=[],
        snow_level=[],
        gust=[],
        ridge=[],
        depth=None,
        observed=[],
        roses=[],
        min_snow_cm=bc.rose_min_snow_cm,
        min_wind_kmh=bc.rose_min_wind_kmh,
    )
    px = pixel(index, lat, lon)
    if px is None:
        wide_px = pixel(wide[0], lat, lon) if wide is not None else None
        if wide is not None and wide_px is not None:
            # Beyond the box: what the wide loop's radar and nowcast say.
            out.wide = True
            probes = Probes(wide[1], *wide_px, int(wide[0].get("height", 0)))
            out.rates = [r for r in _rates(wide[0], probes) if r.kind != "forecast"]
        return out
    out.inside = True
    row, col = px
    probes = Probes(precip_dir, row, col, int(index.get("height", 0)))
    out.rates = _rates(index, probes)

    for t in index.get("totals", []):
        cm = None
        with contextlib.suppress(OSError, ValueError, IndexError, KeyError):
            grid = np.load(totals_dir / f"{int(t.get('window') or t['hours'])}h.npy", mmap_mode="r")
            if grid.shape == (index["height"], index["width"]):
                cm = _num(float(grid[row, col]))
        out.totals.append(
            PointTotal(
                window=int(t.get("window") or t["hours"]),
                hours=int(t["hours"]),
                start=int(t["start"]),
                end=int(t["end"]),
                cm=cm,
                source=str(t.get("source", "")),
                by_elevation=by_elevation(totals_dir, str(t.get("tiles_id") or ""), lat, lon),
            )
        )
    if any(t.by_elevation is not None for t in out.totals):
        out.elevations = [int(z) for z in bins.ELEVS]

    layers = index.get("layers") or {}

    def frames(name: str) -> list[dict[str, Any]]:
        layer = layers.get(name)
        got = layer.get("frames", []) if isinstance(layer, dict) else []
        return sorted(got, key=lambda f: (f.get("hours", 0), f.get("t", 0)))

    for f in frames("snowlevel"):
        cell = probes.cell(f["file"])
        out.snow_level.append(
            PointValue(t=f["t"], value=_num(cell[0], -1) if cell is not None else None)
        )
    for f in frames("gust"):
        cell = probes.cell(f["file"])
        out.gust.append(PointValue(t=f["t"], value=_num(cell[0], 0) if cell is not None else None))
    for f in frames("ridge"):
        cell = probes.cell(f["file"])
        kmh = _num(cell[0], 0) if cell is not None else None
        d = _num(cell[1], 0) if cell is not None and cell.size > 1 else None
        out.ridge.append(PointWind(t=f["t"], kmh=kmh, dir=d))
    for f in frames("depth")[-1:]:
        cell = probes.cell(f["file"])
        out.depth = PointDepth(
            t=f["t"], cm=_num(cell[0], 0) if cell is not None else None, src=f.get("src", {})
        )
    for f in frames("snowfall"):
        cell = probes.cell(f["file"])
        out.observed.append(
            PointObserved(
                hours=int(f.get("hours", 0)),
                end=f["t"],
                cm=_num(cell[0]) if cell is not None else None,
            )
        )
    out.roses = roses(out, now, bc)
    return out


def by_elevation(totals_dir: Path, tiles_id: str, lat: float, lon: float) -> list[float] | None:
    """Snow (cm) at every band's elevation at a point, from a window's grid by elevation."""
    if not tiles_id:
        return None
    grid = bins.load(totals_dir / f"bins-{tiles_id}.npy")
    if grid is None:
        return None
    try:
        meta = json.loads((totals_dir / f"bins-{tiles_id}.json").read_text())
        rows, cols = bins.cell_coords(
            meta["bounds"],
            int(meta["width"]),
            int(meta["height"]),
            np.array([merc_x(lon)]),
            np.array([merc_y(lat)]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    n = len(bins.ELEVS)
    cm = bins.sample(grid, np.repeat(rows, n), np.repeat(cols, n), bins.ELEVS)
    return [round(float(v), 1) for v in cm]


def roses(p: PointOut, now: float, bc: BackcountryConfig) -> list[RoseOut]:
    """Loading roses for the next 24 and 72 hours from the point's own forecast.

    Each forecast frame's snow (its band's middle, half for mix, over its span) is paired
    with the ridge wind nearest in time; the snow is then scaled to the window's snow
    total where there is one, so the amount (which decides whether there's enough to move)
    is the totals' and only the timing comes from the bands."""
    if not p.ridge:
        return []
    out = []
    for name, hours in ROSE_WINDOWS:
        end = now + hours * HOUR
        snow: dict[int, float | None] = {}
        speed: dict[int, float | None] = {}
        direction: dict[int, float | None] = {}
        for r in p.rates:
            if r.kind != "forecast" or r.type not in ("snow", "mix") or r.low is None:
                continue
            start = r.t - r.span_h * HOUR
            if start < now - HOUR or start >= end:
                continue
            mid = r.low * 1.25 if r.high is None else (r.low + r.high) / 2
            share = 0.5 if r.type == "mix" else 1.0
            near = min(p.ridge, key=lambda w: abs(w.t - r.t))
            snow[r.t] = mid * share * max(1, r.span_h)
            if abs(near.t - r.t) <= RIDGE_NEAR_S:
                speed[r.t], direction[r.t] = near.kmh, near.dir
        total = sum(v or 0.0 for v in snow.values())
        want = next((t.cm for t in p.totals if t.window == hours and t.cm is not None), None)
        if want is not None:
            k = want / total if total > 0 else 0.0
            snow = {t: (v or 0.0) * k for t, v in snow.items()}
        rose = loading_rose(sorted(snow), snow, speed, direction, bc)
        out.append(
            RoseOut(
                window=name,
                sectors=[round(x, 3) for x in rose.sectors],
                snow_cm=rose.snow_cm,
                mean_kmh=None if rose.mean_kmh is None else round(rose.mean_kmh),
                wind_from=rose.wind_from,
                loading=rose.loading,
                label=rose.label,
            )
        )
    return out
