"""The map's weather layers beside precipitation (docs/MAP-PLAN.md A5), drawn by the
`layers` job into the same folder and index as the frames (render.py):

  snowlevel  snow level, every 3 h to ~84 h: HRDPS-WEonG then RDPS-WEonG in Canada,
             NBM's SNOWLVL in the US, blended as numbers like the frames (blend.py)
  gust       wind gusts at 10 m, every 3 h to ~84 h: the same sources
  ridge      the free-air wind at 700 hPa (about 3,000 m), every 3 h to ~84 h: RDPS,
             which covers the whole box (with its direction kept for tap-for-numbers)
  depth      snow on the ground, daily: SNODAS in the US, CaLDAS in Canada
  snowfall   snow that fell in the last 24, 48 and 72 h: NOHRSC (US only)
  clouds     GOES-West GeoColor, every half hour over the last 3 h

Each picture is redrawn only when its inputs change (its key), like the frames. A layer
whose sources don't answer keeps the pictures it has.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from snowwatch.maps.blend import Layer, feather, feather_px, mosaic, north_weight
from snowwatch.maps.geomet import (
    Grid,
    capabilities_dims,
    iso_ts,
    on_region,
    parse_times,
    ts_iso,
    wcs_grid,
)
from snowwatch.maps.palette import DEPTH, SNOWLEVEL, TOTAL, WIND
from snowwatch.maps.region import Region, spread, stitch
from snowwatch.maps.sources import gibs, nohrsc, snodas
from snowwatch.maps.sources.nbm import Nbm

if TYPE_CHECKING:
    from snowwatch.maps.render import LayerFrame, Renderer

log = logging.getLogger("snowwatch.precip")

HOUR = 3600
# Part of every snow level and gust picture's key: change it when how they're drawn changes,
# so pictures already on disk are redrawn.
DRAWING = 2
STEP_H = 3  # snow level and wind frames are 3-hourly
MS_TO_KMH = 3.6


@dataclass(frozen=True)
class Field:
    """A quantity from Canada's models and NBM, as one layer."""

    name: str  # the layer's name in the index
    prefix: str  # file name prefix
    hrdps: str  # GeoMet layers (WCS)
    rdps: str
    nbm_var: str  # NBM variable and level
    nbm_level: str
    valid: tuple[float, float]  # plausible values in the source's units
    scale: float  # source units → the picture's (m → m, m/s → km/h)
    ramp: list[tuple[float, str]]
    codes_to: float | None = None  # what GeoMet's negative codes mean (snow level: 0 m)


SNOW_LEVEL = Field(
    "snowlevel",
    "sl",
    "HRDPS-WEonG_2.5km_SnowLevelHeight",
    "RDPS-WEonG_10km_SnowLevelHeight",
    "SNOWLVL",
    "0 m above mean sea level",
    (0.0, 9000.0),
    1.0,
    SNOWLEVEL,
    codes_to=0.0,
)
GUST = Field(
    "gust",
    "g",
    "HRDPS-WEonG_2.5km_WindGust",
    "RDPS-WEonG_10km_WindGust",
    "GUST",
    "10 m above ground",
    (0.0, 120.0),
    MS_TO_KMH,
    WIND,
)
# Coded snow-level cells take a real value from up to this many cells away (HRDPS 2.5 km:
# ~15 km; RDPS 10 km: ~60 km): wide enough to cover a mountain range.
CODE_FILL_CELLS = 6
RIDGE_SPEED = "RDPS_10km_WindSpeed_700mb"  # m/s
RIDGE_DIR = "RDPS_10km_WindDir_700mb"  # degrees, where the wind blows from
CALDAS = "CaLDAS-NSRPS_2.5km_SnowDepth"  # metres


@dataclass
class Run:
    """A GeoMet layer's newest run: its start (ISO) and its valid times."""

    ref: str
    times: list[int]


def run_of(r: Renderer, layer: str) -> Run | None:
    dims = capabilities_dims(r.net, layer)
    times = parse_times(dims.get("time", ""))
    if not times and dims.get("time.default"):
        # A single analysis ("t/t/PT0H"): the time is its default.
        try:
            times = [iso_ts(dims["time.default"])]
        except ValueError:
            times = []
    return Run(dims.get("reference_time.default", ""), times) if times else None


def grid(
    r: Renderer,
    layer: str,
    run: Run,
    t: int,
    region: Region,
    valid: tuple[float, float],
    smooth: bool = True,
    codes_to: float | None = None,
) -> np.ndarray | None:
    """One GeoMet layer at time t on the region (NaN where it has no value)."""
    g = wcs_grid(r.net, layer, ts_iso(t), region, ref=run.ref or None, cache_dir=r.wcs_dir)
    if g is None:
        return None
    if codes_to is not None:
        g = Grid(fill_codes(g.data, CODE_FILL_CELLS, codes_to), g.lon0, g.lat0, g.dlon, g.dlat)
    return on_region(g, region, valid, smooth=smooth)


def fill_codes(values: np.ndarray, passes: int, rest: float) -> np.ndarray:
    """GeoMet's snow level holds -1 or -2 where snow reaches the ground ("partially
    melted" or not at all): the snow level is somewhere below the ground there, not at sea
    level. On a mountain range standing above the snow level around it, the best guess is
    that surrounding level, so coded cells take their nearest real value within `passes`
    cells; wider areas (a cold air mass), beyond that reach, take `rest` (0 m: snow to
    the valleys)."""
    out = np.where(values < 0, -1.0, values).astype(np.float32)
    if (out == -1).any():
        out = spread(out, passes, empty=-1.0)
        out[out == -1] = rest
    return out


def draw(r: Renderer, region: Region) -> dict[str, list[LayerFrame]]:
    """Every layer that could be drawn this time; the others keep what they have."""
    old = r._layers_of(r._read(), region)
    out: dict[str, list[LayerFrame]] = {}
    parts: list[tuple[str, Callable[[], list[LayerFrame] | None]]] = [
        ("snowlevel", lambda: model_field(r, region, SNOW_LEVEL, old.get("snowlevel", []))),
        ("gust", lambda: model_field(r, region, GUST, old.get("gust", []))),
        ("ridge", lambda: ridge(r, region, old.get("ridge", []))),
        ("depth", lambda: depth(r, region, old.get("depth", []))),
        ("snowfall", lambda: snowfall(r, region, old.get("snowfall", []))),
        ("clouds", lambda: clouds(r, region, old.get("clouds", []))),
    ]
    for name, job in parts:
        try:
            frames = job()
        except Exception:
            log.exception("map layer %s failed", name)
            frames = None
        if frames:
            out[name] = frames
        elif name in old:
            log.warning("map layer %s: nothing new; keeping %d pictures", name, len(old[name]))
    return out


def _reuse(r: Renderer, old: list[LayerFrame]) -> dict[str, LayerFrame]:
    return {f.key: f for f in old if (r.dir / f.file).exists()}


def _parallel(jobs: list[Callable[[], LayerFrame | None]], workers: int = 2) -> list[LayerFrame]:
    with ThreadPoolExecutor(workers) as pool:
        return [f for f in pool.map(lambda j: j(), jobs) if f is not None]


# ---- Snow level and gusts ---------------------------------------------------------------


def model_field(
    r: Renderer, region: Region, spec: Field, old: list[LayerFrame]
) -> list[LayerFrame] | None:
    """Every 3 h to the end of RDPS's run: HRDPS where its domain reaches, RDPS beneath
    it (which covers everything), NBM in the US, fading across 48.5–49.5°N."""
    from snowwatch.maps.render import LayerFrame

    now = int(r.now())
    hr = run_of(r, spec.hrdps)
    rd = run_of(r, spec.rdps)
    if rd is None and hr is None:
        return None
    base = rd or hr
    assert base is not None
    times = [t for t in base.times if t > now and t % (STEP_H * HOUR) == 0]
    us: Nbm | None = r._nbm(region)
    prev = _reuse(r, old)
    w_hrdps = r._hrdps_weight(region) if hr is not None else None

    def job(t: int) -> Callable[[], LayerFrame | None]:
        def go() -> LayerFrame | None:
            use_h = hr is not None and w_hrdps is not None and t in hr.times
            use_r = rd is not None and t in rd.times
            lead = us.lead(t) if us is not None else 0
            use_n = us is not None and 1 <= lead <= 192
            key = "|".join(
                [
                    f"{spec.name}@{DRAWING}",
                    str(t),
                    f"h:{hr.ref}" if use_h and hr else "-",
                    f"r:{rd.ref}" if use_r and rd else "-",
                    f"n:{us.run}:{lead}" if use_n and us else "-",
                    region.key,
                ]
            )
            had = prev.get(key)
            if had is not None:
                return had
            layers: list[Layer] = []
            src: dict[str, str] = {}
            runs: dict[str, int] = {}
            if use_n and us is not None:
                v = us.field(lead, spec.nbm_var, spec.nbm_level)
                if v is not None:
                    v = np.where((v >= spec.valid[0]) & (v <= spec.valid[1]), v, np.nan)
                    layers.append(Layer("nbm", v * spec.scale, r._us_weight(region, v)))
                    src["south"] = "nbm"
                    runs["nbm"] = us.run
            north = ""
            if use_h and hr is not None and w_hrdps is not None:
                v = grid(r, spec.hrdps, hr, t, region, spec.valid, codes_to=spec.codes_to)
                if v is not None:
                    layers.append(Layer("hrdps", v * spec.scale, w_hrdps))
                    north = "hrdps"
                    runs["hrdps"] = _ts(hr.ref)
            if use_r and rd is not None:
                v = grid(r, spec.rdps, rd, t, region, spec.valid, codes_to=spec.codes_to)
                if v is not None:
                    layers.append(Layer("rdps", v * spec.scale, 1.0))
                    north = north or "rdps"
                    runs["rdps"] = _ts(rd.ref)
            if not north:
                return None  # try again next time rather than draw only the US
            src["north"] = north
            src.setdefault("south", north)
            value = mosaic(layers).amount
            name = r._save_ramp(value, spec.ramp, f"{spec.prefix}{t}")
            return LayerFrame(t, name, key, "forecast", 0, 0, src, runs)

        return go

    return _parallel([job(t) for t in times])


def _ts(ref: str) -> int:
    try:
        return iso_ts(ref)
    except ValueError:
        return 0


# ---- Ridge-level wind -----------------------------------------------------------------


def ridge(r: Renderer, region: Region, old: list[LayerFrame]) -> list[LayerFrame] | None:
    """RDPS's 700 hPa wind every 3 h: one model over the whole box, so no blending. Its
    direction is kept beside the speed for tap-for-numbers and the wind-effect layer."""
    from snowwatch.maps.render import LayerFrame

    now = int(r.now())
    run = run_of(r, RIDGE_SPEED)
    if run is None:
        return None
    prev = _reuse(r, old)

    def job(t: int) -> Callable[[], LayerFrame | None]:
        def go() -> LayerFrame | None:
            key = f"ridge|{t}|{run.ref}|{region.key}"
            had = prev.get(key)
            if had is not None:
                return had
            speed = grid(r, RIDGE_SPEED, run, t, region, (0.0, 150.0))
            if speed is None:
                return None
            # Directions are taken from the nearest cell: interpolating between 350° and
            # 10° would give 180°.
            direction = grid(r, RIDGE_DIR, run, t, region, (0.0, 360.0), smooth=False)
            if direction is None:
                direction = np.full_like(speed, np.nan)
            kmh = speed * MS_TO_KMH
            values = np.stack([kmh, direction])
            name = r._save_ramp(kmh, WIND, f"w{t}", values)
            src = {"north": "rdps", "south": "rdps"}
            return LayerFrame(t, name, key, "forecast", 0, 0, src, {"rdps": _ts(run.ref)})

        return go

    times = [t for t in run.times if t > now and t % (STEP_H * HOUR) == 0]
    return _parallel([job(t) for t in times])


# ---- Snow on the ground ---------------------------------------------------------------


def depth(r: Renderer, region: Region, old: list[LayerFrame]) -> list[LayerFrame] | None:
    """One picture: SNODAS (1 km) in the US, CaLDAS (2.5 km) in Canada, fading across
    48.5–49.5°N and over SNODAS's last ~100 km."""
    from snowwatch.maps.render import LayerFrame

    day = snodas.latest(r.net, int(r.now()))
    cal = run_of(r, CALDAS)
    if day is None and cal is None:
        return None
    key = f"depth|{day or '-'}|{cal.ref if cal else '-'}|{region.key}"
    had = _reuse(r, old).get(key)
    if had is not None:
        return [had]
    layers: list[Layer] = []
    src: dict[str, str] = {}
    runs: dict[str, int] = {}
    if day is not None:
        tar = snodas.fetch(r.net, day)
        g = snodas.depth_grid(tar) if tar else None
        if g is not None:
            mm = on_region(g, region, (0, 40000))  # nearest cell: 1 km data, 1.5 km pixels
            cm = mm / 10
            w = feather(np.isfinite(cm), feather_px(region)) * (1 - north_weight(region))
            layers.append(Layer("snodas", cm, w))
            src["south"] = "snodas"
            runs["snodas"] = snodas.day_ts(day)
    if cal is not None:
        m = grid(r, CALDAS, cal, cal.times[-1], region, (0.0, 100.0))
        if m is not None:
            layers.append(Layer("caldas", m * 100, 1.0))
            src["north"] = "caldas"
            runs["caldas"] = cal.times[-1]
    if not layers:
        return None
    cm = mosaic(layers).amount
    t = max(runs.values())
    name = r._save_ramp(cm, DEPTH, f"d{t}")
    return [LayerFrame(t, name, key, "observed", 0, 0, src, runs)]


# ---- Observed snowfall ----------------------------------------------------------------


def snowfall(r: Renderer, region: Region, old: list[LayerFrame]) -> list[LayerFrame] | None:
    """NOHRSC's analysis of the last 24, 48 and 72 hours (the US only)."""
    from snowwatch.maps.render import LayerFrame

    names = nohrsc.latest(r.net, int(r.now()))
    if not names:
        return None
    prev = _reuse(r, old)
    out: list[LayerFrame] = []
    for hours, file in sorted(names.items()):
        key = f"obs|{file}|{region.key}"
        had = prev.get(key)
        if had is not None:
            out.append(had)
            continue
        g = nohrsc.fetch(r.net, file)
        if g is None:
            continue
        cm = on_region(g, region, (0.0, 500.0), smooth=True) * nohrsc.CM_PER_IN
        end = nohrsc.end_ts(file)
        name = r._save_ramp(cm, TOTAL, f"o{end}")
        src = {"south": "nohrsc"}
        out.append(LayerFrame(end, name, key, "observed", 0, hours, src, {"nohrsc": end}))
    return out


# ---- Clouds -----------------------------------------------------------------------------


def clouds(r: Renderer, region: Region, old: list[LayerFrame]) -> list[LayerFrame] | None:
    """GOES-West GeoColor every half hour over the last 3 hours, stitched from GIBS's
    tiles onto the frames' grid and kept as WebP (it's imagery, not a palette)."""
    from snowwatch.maps.render import LayerFrame

    now = int(r.now())
    available = gibs.times(r.net, now - gibs.HISTORY_S - gibs.SLACK_S - gibs.STEP_S, now)
    wanted = gibs.pick(available, now)
    if not wanted:
        return None
    prev = _reuse(r, old)

    def job(t: int) -> Callable[[], LayerFrame | None]:
        def go() -> LayerFrame | None:
            key = f"clouds|{t}|{region.key}"
            had = prev.get(key)
            if had is not None:
                return had
            img = stitch(r.net, gibs.template(t), region, gibs.ZOOM)
            if img is None:
                return None
            name = r._save_webp(img, f"c{t}")
            return LayerFrame(t, name, key, "observed", 0, 0, {"north": "goes"}, {"goes": t})

        return go

    return _parallel([job(t) for t in wanted])
