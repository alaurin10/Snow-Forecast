"""The map's frames: drawn into one folder and listed in `index.json` for the browser.

Four jobs share the folder, each on its own schedule (see scheduler.py):

  radar     observed radar and the nowcast, every 6 minutes
  forecast  the forecast frames (hourly to 48 h, then 3- and 6-hourly to 10 days), every 30 minutes
  totals    the snow totals (12 h to 10 days), hourly
  layers    the other weather layers (snow level, wind, snow on the ground, observed
            snowfall, clouds; see layers.py), every 30 minutes

Each draws only what changed (frames are keyed by their inputs), then rewrites its own
part of the index under a file lock and leaves the other parts as they are.

Each picture's file name includes a hash of its pixels, so browsers can cache it for good.
Files that drop out of the index are kept for a quarter of an hour, so a page that loaded
the previous index can still fetch them.

Beside each picture, `probe/<file>.npy` keeps every fourth pixel of it as numbers (palette
indices for precipitation, values for the other layers) for tap-for-numbers (point.py).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import io
import json
import logging
import os
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from snowwatch.config import SlrBand
from snowwatch.maps import (
    bins,
    coverage,
    dataframe,
    grib,
    terrain_totals,
    totaldata,
    totals,
)
from snowwatch.maps.blend import (
    Layer,
    Mosaic,
    feather,
    feather_px,
    fill_kinds,
    mosaic,
    north_weight,
)
from snowwatch.maps.files import save_npy, write_atomic
from snowwatch.maps.geomet import Net, iso_ts, prune_wcs_cache, ts_iso
from snowwatch.maps.palette import (
    FINE,
    FINE_EXT,
    FINE_FROM,
    FINE_KIND,
    MIX_T,
    NONE,
    RAIN_T,
    RATE_BANDS,
    SNOW_T,
    decode_indices,
    encode,
    encode_fine,
    fine_index,
    index_ramp,
    kinds_of,
    paint_total,
    repaint,
    snap,
)
from snowwatch.maps.point import PROBE_STEP
from snowwatch.maps.region import Region, stitch
from snowwatch.maps.smooth import blur, soften
from snowwatch.maps.sources import hrrr, mrms, nbm, radar_eccc, rainviewer, rdps_gdps
from snowwatch.maps.sources.nbm import Nbm
from snowwatch.maps.sources.rdps_gdps import GDPS, HRDPS, RDPS, RDPS_HOURLY, Run, run_of

log = logging.getLogger("snowwatch.precip")

HOUR = 3600
INDEX_VERSION = 3
RETIRE_S = 15 * 60  # how long a file that left the index stays on disk
# Precipitation frames drawn on the fine palette: in each frame's key, so frames drawn
# the old way are drawn again rather than reused.
FINE_KEY = "f6"
# How much each source is softened before it is painted (smooth.py), in pixels (~1.5 km):
# radar's 1 km scans just enough to lose the pixel steps; HRRR and NBM, copied from the
# nearest 2.5–3 km cell, enough to lose their ~2 px blocks. GeoMet's models arrive
# interpolated already.
# Radar frames drawn with the current typing (radar_eccc.fill_types: echoes nothing types
# are left out): in their keys, so older radar frames are drawn again.
RADAR_TYPING = "t4"
# Radar and nowcast frames with their blind spots filled from the forecast (fill_gaps): in
# their keys, so frames drawn before are drawn again.
GAPS = "g1"
RADAR_SIGMA = 0.8
GRIB_SIGMA = 1.2
# Radar's types come from a coarser product, and echoes it leaves untyped take the
# nearest type within ~12 km (filled pixel by pixel, in diamonds): their borders are
# rounded off over a few pixels.
RADAR_KIND_SIGMA = 4.0

DOMAIN_LAYER = HRDPS.precip  # drawn solid, it shows where HRDPS has data
# Splitting NBM's 6-hour amount between two 3-hour frames follows RDPS's split, softened
# by this much water (mm) so a trace in one half doesn't take everything.
SPLIT_SOFT_MM = 0.25

TOTAL_HOURS = totals.WINDOWS
# Part of every grid by elevation's name: change it when how they're built changes.
BINS_DRAWING = 1
# Part of the snow total's steps' key (totaldata.py): change it when how they're drawn does.
STEPS_DRAWING = 1
TILES_URL = "/api/snowtiles/{id}/{{z}}/{{x}}/{{y}}.png"
SN_TOTAL_LAYER = HRDPS.accum  # water equivalent (mm) since the run began

# Credit lines for the sources a frame or total came from (`src` values).
ATTRIBUTION = {
    "radar-eccc": "Radar: Environment and Climate Change Canada (North American composite)",
    "nowcast-eccc": "Nowcast: Environment and Climate Change Canada radar extrapolation",
    "rainviewer": "Radar: RainViewer",
    "mrms": "Radar quality control and types (US): NOAA MRMS (NOAA Open Data Dissemination)",
    "hrdps": "Forecast: Environment and Climate Change Canada HRDPS",
    "rdps": "Forecast: Environment and Climate Change Canada RDPS",
    "gdps": "Forecast: Environment and Climate Change Canada GDPS",
    "hrrr": "Forecast: NOAA HRRR (NOAA Open Data Dissemination)",
    "nbm": "Forecast: NOAA National Blend of Models (NOAA Open Data Dissemination)",
    "snodas": "Snow on the ground: NOAA NOHRSC SNODAS (US), via NSIDC",
    "caldas": "Snow on the ground: Environment and Climate Change Canada CaLDAS",
    "nohrsc": "Observed snowfall: NOAA NOHRSC National Snowfall Analysis (US)",
    "goes": "Clouds: NOAA GOES-West GeoColor (CIRA), via NASA GIBS",
}

RADAR_KINDS = {"radar", "nowcast"}
FORECAST_KINDS = {"forecast"}
# How much of the map's grid each kind of frame's numbers keep (dataframe.py, `ds`): radar
# at 1 km is worth every pixel; HRDPS, HRRR and NBM (2.5–3 km) half; RDPS and GDPS
# (10–15 km) a quarter.
DS_RADAR, DS_HOURLY, DS_EXTENDED = 1, 2, 4
# Which model draws where, in each hourly frame's key: "b1", NOAA's south of the border and
# Canada's north of it at every lead time (before, HRDPS wherever it reached for 48 h).
OWNERS = "b1"


@dataclass
class FrameOut:
    t: int
    # True for observed radar. Kept beside `kind` for pages loaded before index v2.
    past: bool
    file: str
    key: str
    # Where the US forecast came from: "hrrr", "nbm" or "" (none / radar).
    south: str
    kind: str = "forecast"  # "radar" | "nowcast" | "forecast"
    # Hours the frame's amount covers: 1 for hourly forecast frames, 3 and 6 beyond them,
    # 0 for a rate at an instant (radar, nowcast).
    span_h: int = 1
    # Which source drew the north (Canada) and south (US) parts.
    src: dict[str, str] = field(default_factory=dict)
    # "fine" for frames on palette.FINE_PALETTE; "" for the older PALETTE.
    palette: str = ""
    # The frame as numbers (dataframe.py), which the map colours itself: the file, and how
    # many of the region's pixels one of its rate pixels spans.
    data: str = ""
    ds: int = 1
    # The instant the frame stands for: a scan's or a nowcast's time, the middle of a
    # forecast frame's span. The map interpolates between frames by it.
    valid: int = 0
    # A forecast frame the timeline no longer shows (the nowcast has reached past it) but
    # the nowcast's hand-over still reads: listed under "under" in the index.
    hidden: bool = False

    @classmethod
    def load(cls, d: dict[str, Any]) -> FrameOut:
        """From the index, including one written before v2."""
        d = dict(d)
        d.setdefault("kind", "radar" if d.get("past") else "forecast")
        names = {f.name for f in fields(cls)}
        out = cls(**{k: v for k, v in d.items() if k in names})
        out.valid = out.valid or valid_time(out.t, out.kind, out.span_h)
        return out


@dataclass
class TotalOut:
    hours: int  # the window's actual length (shorter than `window` if the models stop sooner)
    start: int
    end: int
    file: str
    key: str
    # The models used, joined by "+" ("hrdps+rdps+gdps+nbm").
    source: str = "hrdps"
    # The terrain-adjusted tiles' URL template (`{z}/{x}/{y}`), when there are some.
    tiles: str | None = None
    window: int = 0  # the window asked for, in hours: 12, 24, 48, 72, 120, 168, 240
    # Each model used → when its run began (Unix seconds).
    runs: dict[str, int] = field(default_factory=dict)
    # Names the grid by elevation behind `tiles` (data/maps/totals/bins-<id>.npy).
    tiles_id: str = ""

    @classmethod
    def load(cls, d: dict[str, Any]) -> TotalOut:
        names = {f.name for f in fields(cls)}
        out = cls(**{k: v for k, v in d.items() if k in names})
        out.window = out.window or out.hours
        return out


@dataclass
class LayerFrame:
    """One picture of a weather layer other than precipitation (see layers.py)."""

    t: int  # valid time; for observed snowfall the window's end
    file: str
    key: str
    kind: str = "forecast"  # "forecast" | "observed"
    span_h: int = 0  # 0: a value at an instant
    hours: int = 0  # observed snowfall: the window's length
    src: dict[str, str] = field(default_factory=dict)
    # Each source used → its run start or analysis time (Unix seconds).
    runs: dict[str, int] = field(default_factory=dict)
    # The same frame as numbers, for the map to colour itself (temperature: totaldata.py).
    data: str = ""

    @classmethod
    def load(cls, d: dict[str, Any]) -> LayerFrame:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def valid_time(t: int, kind: str, span_h: int) -> int:
    """The instant a frame stands for: forecast frames are stamped with the end of their
    span and stand for its middle."""
    return t - span_h * HOUR // 2 if kind == "forecast" else t


def probe_sample(values: np.ndarray, step: int = PROBE_STEP) -> np.ndarray:
    """Every `step`-th pixel each way, from the middle of each block (the last two axes:
    rows, columns)."""
    k = step // 2
    out: np.ndarray = values[..., k::step, k::step]
    return out


def _run_ts(ref: str) -> int:
    """A run's start (ISO) as Unix seconds; 0 if GeoMet didn't say."""
    try:
        return iso_ts(ref)
    except ValueError:
        return 0


class Renderer:
    """Draws frames into `out_dir` and keeps `index.json` up to date."""

    def __init__(
        self,
        out_dir: Path,
        net: Net,
        now: Callable[[], float] = time.time,
        *,
        work_dir: Path | None = None,
        nbm_cycles: tuple[int, ...] = (0, 12),
        slr_bands: list[SlrBand] | None = None,
        probe_step: int = PROBE_STEP,
    ) -> None:
        self.dir = out_dir
        # Every how many pixels a frame's probe keeps (point.py reads any step): the wide
        # loop's pixels are ~4 km, so it keeps every one.
        self.probe_step = probe_step
        self.net = net
        self.now = now
        self.nbm_cycles = nbm_cycles
        self.slr_bands = slr_bands or []
        # Working files the browser never sees: model grid maps, cached downloads (GRIB
        # messages and GeoMet grids), and the snow totals as numbers.
        work = work_dir or out_dir / ".work"
        self.grids_dir = work / "grids"
        self.grib_dir = work / "grib"
        self.wcs_dir = work / "wcs"
        self.totals_dir = work / "totals"
        self._weights: dict[str, np.ndarray] = {}
        self._wlock = threading.Lock()
        self._nbm_obj: Nbm | None = None
        self.totals: list[TotalOut] = []
        self._prev_totals: dict[str, TotalOut] = {}
        self._nbm_run: int | None = None
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---- The index ---------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads((self.dir / "index.json").read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _frames_of(self, index: dict[str, Any], region: Region) -> list[FrameOut]:
        """The index's frames, if they were drawn over this region."""
        if index.get("region") != region.key:
            return []
        out = []
        for f in [*index.get("frames", []), *index.get("under", [])]:
            try:
                out.append(FrameOut.load(f))
            except (TypeError, KeyError):
                continue
        return out

    def _layers_of(self, index: dict[str, Any], region: Region) -> dict[str, list[LayerFrame]]:
        """The index's other weather layers, if they were drawn over this region."""
        if index.get("region") != region.key:
            return {}
        out: dict[str, list[LayerFrame]] = {}
        for name, layer in (index.get("layers") or {}).items():
            frames = []
            for f in layer.get("frames", []) if isinstance(layer, dict) else []:
                try:
                    frames.append(LayerFrame.load(f))
                except (TypeError, KeyError):
                    continue
            out[name] = frames
        return out

    def _totals_of(self, index: dict[str, Any], region: Region) -> list[TotalOut]:
        if index.get("region") != region.key:
            return []
        out = []
        for t in index.get("totals", []):
            try:
                out.append(TotalOut.load(t))
            except (TypeError, KeyError):
                continue
        return out

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """One writer of the index at a time, across threads and processes."""
        with open(self.dir / "index.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _commit(
        self,
        region: Region,
        kinds: set[str],
        frames: list[FrameOut] | None = None,
        totals: list[TotalOut] | None = None,
        layers: dict[str, list[LayerFrame]] | None = None,
        steps: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Replace the index's frames of these kinds (and the totals, the named layers
        and the snow total's steps, if given)."""
        with self._locked():
            cur = self._read()
            old_frames = self._frames_of(cur, region)
            old_totals = self._totals_of(cur, region)
            new_frames = [f for f in old_frames if f.kind not in kinds] + (frames or [])
            new_totals = old_totals if totals is None else totals
            new_layers = {**self._layers_of(cur, region), **(layers or {})}
            old_steps = cur.get("steps") if cur.get("region") == region.key else None
            index = self._index(
                region, new_frames, new_totals, new_layers, old_steps if steps is None else steps
            )
            keep = _files(index)
            was = _files(cur)
            # Files leaving the index get a fresh clock: pages may still ask for them.
            for name in was - keep:
                if isinstance(name, str):
                    with contextlib.suppress(OSError):
                        os.utime(self.dir / name)
            tmp = self.dir / "index.json.tmp"
            tmp.write_text(json.dumps(index))
            tmp.replace(self.dir / "index.json")
            self._prune(keep)
        return index

    def _index(
        self,
        region: Region,
        frames: list[FrameOut],
        totals: list[TotalOut],
        layers: dict[str, list[LayerFrame]] | None = None,
        steps: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = max((f.t for f in frames if f.kind == "radar"), default=None)
        if now is not None:
            # A forecast hour that ended before the latest radar scan is over (the last
            # such hour stays on hand: the nowcast's hand-over reads either side of it).
            frames = [f for f in frames if f.kind == "radar" or f.t > now - HOUR]
        # The timeline runs radar, nowcast, forecast, each after the last: a forecast
        # frame standing for a time the nowcast has already reached would show the model
        # in the middle of the nowcast. It stays on hand (`under`) for the hand-over.
        reached = max((f.t for f in frames if f.kind in RADAR_KINDS), default=None)
        for f in frames:
            f.valid = f.valid or valid_time(f.t, f.kind, f.span_h)
            f.hidden = f.kind == "forecast" and (
                (reached is not None and f.valid <= reached) or (now is not None and f.t <= now)
            )
        frames = sorted(frames, key=lambda f: (f.valid, f.kind != "radar"))
        under = [f for f in frames if f.hidden]
        frames = [f for f in frames if not f.hidden]
        srcs: list[str] = []
        for f in frames:
            for s in f.src.values():
                if s and s not in srcs:
                    srcs.append(s)
        for t in totals:
            for s in t.runs or [t.source]:
                if s not in srcs:
                    srcs.append(s)
        layers = {k: sorted(v, key=lambda f: (f.hours, f.t)) for k, v in (layers or {}).items()}
        for lf in (f for v in layers.values() for f in v):
            for s in lf.src.values():
                if s and s not in srcs:
                    srcs.append(s)
        return {
            "version": INDEX_VERSION,
            "generated": ts_iso(int(self.now())),
            "region": region.key,
            "bounds": region.bounds,
            "width": region.width,
            "height": region.height,
            "now": now,
            "frames": [asdict(f) for f in frames],
            "under": [asdict(f) for f in under],
            "totals": [asdict(t) for t in sorted(totals, key=lambda t: (t.window, t.hours))],
            "layers": {k: {"frames": [asdict(f) for f in v]} for k, v in layers.items()},
            # The snow total as numbers, from `start` to each step's `end`
            # (totaldata.py): {"start", "key", "steps": [{"end", "hours", "data"}]}.
            "steps": steps,
            "attribution": [ATTRIBUTION[s] for s in srcs if s in ATTRIBUTION],
        }

    def _save(
        self,
        img: np.ndarray,
        region: Region,
        prefix: str,
        values: np.ndarray | None = None,
    ) -> str:
        """A palette PNG named by its pixels, and its probe: the numbers in `values`
        (channels first, or one 2-D grid), else the palette indices."""
        indexed = snap(img, region)
        data = encode(indexed)
        name = f"{prefix}-{hashlib.sha1(data).hexdigest()[:12]}.png"
        self._store(name, data)
        if values is None:
            self._write_probe(name, probe_sample(indexed, self.probe_step))
        else:
            self._write_probe(name, probe_sample(values, self.probe_step).astype(np.float16))
        return name

    def _save_precip(
        self,
        amount: np.ndarray,
        kind: np.ndarray,
        prefix: str,
        sigma: float = 0.0,
        kind_sigma: float | None = None,
        ds: int = 1,
        filled: np.ndarray | None = None,
    ) -> tuple[str, str]:
        """A precipitation frame (rates and types) softened by `sigma` pixels (types by
        `kind_sigma`): drawn on the fine palette, with its probe (the palette indices),
        and as numbers at 1/ds of the grid (dataframe.py). Returns both files' names.
        `filled` is the share of each pixel's water the forecast filled in (fill_gaps):
        a plane of the numbers, and the probe's second channel (0..255)."""
        amount, kind = soften(amount, kind, sigma, kind_sigma)
        if filled is not None:
            filled = blur(filled, sigma) if sigma > 0 else filled
            if not filled.any():
                filled = None
        indexed = fine_index(amount, kind)
        data = encode_fine(indexed)
        name = f"{prefix}-{hashlib.sha1(data).hexdigest()[:12]}.{FINE_EXT}"
        self._store(name, data)
        if filled is None:
            self._write_probe(name, probe_sample(indexed, self.probe_step))
        else:
            share = np.clip(np.rint(filled * 255), 0, 255).astype(np.uint8)
            self._write_probe(name, probe_sample(np.stack([indexed, share]), self.probe_step))
        numbers = dataframe.encode(amount, kind, ds, filled)
        numbers_name = f"{prefix}-{hashlib.sha1(numbers).hexdigest()[:12]}.{dataframe.EXT}"
        self._store(numbers_name, numbers)
        return name, numbers_name

    def _save_ramp(
        self,
        values: np.ndarray,
        ramp: list[tuple[float, str]],
        prefix: str,
        probe: np.ndarray | None = None,
    ) -> str:
        """Values painted on one of the palette's ramps, with the values (or `probe`) as
        the probe. Straight to palette indices: these layers are solid everywhere, where
        matching each pixel's colour (`snap`) costs seconds."""
        data = encode(index_ramp(values, ramp))
        name = f"{prefix}-{hashlib.sha1(data).hexdigest()[:12]}.png"
        self._store(name, data)
        keep = values if probe is None else probe
        self._write_probe(name, probe_sample(keep, self.probe_step).astype(np.float16))
        return name

    def _save_cloud(self, cover: np.ndarray, prefix: str) -> str:
        """Forecast cloud cover (%) drawn as cloud over the map, at half the grid's size
        (it has no finer detail, and the map stretches it): clear below CLOUD_FROM, then
        from a thin white veil to thick grey cloud, in 5% steps (small files). The probe
        keeps the cover itself."""
        c = np.nan_to_num(cover, nan=0.0).astype(np.float32)
        half = c[: c.shape[0] // 2 * 2, : c.shape[1] // 2 * 2]
        half = half.reshape(half.shape[0] // 2, 2, half.shape[1] // 2, 2).mean((1, 3))
        steps = np.clip(np.rint(half / 5), 0, 20).astype(np.uint8)
        im = Image.fromarray(steps, "P")
        im.putpalette([v for c_ in CLOUD_RGB for v in c_])
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True, transparency=CLOUD_ALPHA)
        data = buf.getvalue()
        name = f"{prefix}-{hashlib.sha1(data).hexdigest()[:12]}.png"
        self._store(name, data)
        self._write_probe(name, probe_sample(c, self.probe_step).astype(np.float16))
        return name

    def _save_webp(self, img: np.ndarray, prefix: str, quality: int = 72) -> str:
        """A colour picture (satellite imagery) as WebP, named by its bytes."""
        buf = io.BytesIO()
        Image.fromarray(img[..., :3]).save(buf, "WEBP", quality=quality, method=4)
        data = buf.getvalue()
        name = f"{prefix}-{hashlib.sha1(data).hexdigest()[:12]}.webp"
        self._store(name, data)
        return name

    def _store(self, name: str, data: bytes) -> None:
        path = self.dir / name
        if path.exists():
            # Same pixels as an older file: freshen it so pruning leaves it be.
            os.utime(path)
        else:
            write_atomic(path, data)

    def _probe_path(self, name: str) -> Path:
        return self.dir / "probe" / f"{name}.npy"

    def _write_probe(self, name: str, values: np.ndarray) -> None:
        path = self._probe_path(name)
        if path.exists():
            with contextlib.suppress(OSError):
                os.utime(path)
            return
        save_npy(path, np.ascontiguousarray(values))

    def _prune(self, keep: set[str]) -> None:
        """Drop pictures (and their probes) the index doesn't use once they've been out
        of it a while."""
        cutoff = time.time() - RETIRE_S
        for p in [
            *self.dir.glob("*.png"),
            *self.dir.glob("*.webp"),
            *self.dir.glob(f"*.{dataframe.EXT}"),
            *self.dir.glob("*.tmp"),
            *self.dir.glob("probe/*.npy"),
            *self.dir.glob("probe/*.tmp"),
        ]:
            if p.name in keep or p.name.removesuffix(".npy") in keep:
                continue
            with contextlib.suppress(OSError):
                if p.stat().st_mtime < cutoff:
                    p.unlink()

    def _reusable(self, prev: dict[str, FrameOut], key: str) -> FrameOut | None:
        f = prev.get(key)
        if f is None or not (self.dir / f.file).exists():
            return None
        if not (f.data and (self.dir / f.data).exists()):
            return None  # drawn before frames were kept as numbers: draw it again
        if not self._probe_path(f.file).exists():
            # Drawn before probes existed: make its probe from the picture.
            try:
                idx = decode_indices((self.dir / f.file).read_bytes())
            except OSError:
                idx = None
            if idx is not None:
                self._write_probe(f.file, probe_sample(idx, self.probe_step))
        return f

    # ---- Everything ----------------------------------------------------------------

    def run(self, region: Region) -> dict[str, Any]:
        """Radar, forecast and totals, one after the other (the other layers are their
        own job: `layers`)."""
        self.radar(region)
        self.forecast(region)
        return self.snow_totals(region)

    def layers(self, region: Region) -> dict[str, Any]:
        """Snow level, wind, snow on the ground, observed snowfall and clouds (layers.py)."""
        from snowwatch.maps import layers

        index = self._commit(region, set(), None, None, layers.draw(self, region))
        self._prune_work()
        return index

    # ---- Radar and nowcast ----------------------------------------------------------

    def _forecast_types(self, frames: list[FrameOut]) -> np.ndarray | None:
        """Type codes from the first forecast frame, for echoes radar couldn't type."""
        ahead = sorted((f for f in frames if f.kind == "forecast"), key=lambda f: f.t)
        if not ahead:
            return None
        try:
            idx = decode_indices((self.dir / ahead[0].file).read_bytes())
        except OSError:
            return None
        if idx is None:
            return None
        out: np.ndarray = FINE_KIND[idx] if ahead[0].palette == FINE else kinds_of(idx)
        return out

    def radar(self, region: Region) -> dict[str, Any]:
        """Observed radar for the last 3 hours and the next 72 minutes' nowcast, which
        hands over to the forecast as it goes."""
        old = self._frames_of(self._read(), region)
        prev = {f.key: f for f in old}
        frames = self._radar_eccc(region, prev, self._forecast_types(old), old)
        if not any(f.kind == "radar" for f in frames):
            log.warning("Environment Canada radar returned nothing; using RainViewer")
            frames = self._radar_rainviewer(region, prev)
        if not frames:
            # Neither answered: the frames we have say more than none (their times show
            # how old they are).
            log.warning("no radar source answered; keeping the current radar frames")
            return self._read()
        return self._commit(region, RADAR_KINDS, frames)

    def _radar_eccc(
        self,
        region: Region,
        prev: dict[str, FrameOut],
        fallback: np.ndarray | None,
        old: list[FrameOut] | None = None,
    ) -> list[FrameOut]:
        p = radar_eccc.plan(self.net)
        if p is None:
            return []
        out: list[FrameOut] = []
        latest_t = max(p.radar) if p.radar else None
        clutter = radar_eccc.Clutter(self._clutter_path(region), (region.height, region.width))
        # The forecast, for the nowcast's hand-over and for what radar can't see.
        model = _Model(self.dir, [f for f in old or [] if f.kind == "forecast"], region)
        seen: np.ndarray | None = None
        if model.frames and latest_t is not None:
            seen = coverage.Coverage(self._coverage_path(region), region, self.now()).get(
                self.net, latest_t
            )

        def filled(t: int, got: tuple[np.ndarray, np.ndarray]) -> tuple[Any, ...]:
            """The frame with its blind spots filled from the forecast at t (if it has a
            frame within the hour), and the share filled (None if not)."""
            pair = model.pair(t) if seen is not None else None
            ahead = model.at(t, pair) if pair else None
            if seen is None or ahead is None:
                return (*got, None)
            return fill_gaps(got[0], got[1], ahead, seen)

        for t in p.radar:
            type_t = radar_eccc.type_time(t, p.types)
            base = f"eccc|{FINE_KEY}|{RADAR_TYPING}|{GAPS}|{t}|{type_t}|{region.key}"
            # Checked against MRMS ("m") when it had the scan; else as ECCC drew it ("n"),
            # tried against MRMS again next time.
            had = self._reusable(prev, f"{base}|m")
            if had:
                out.append(had)
                continue
            scan = mrms.scan(self.net, t, region)
            if scan is None:
                had = self._reusable(prev, f"{base}|n")
                if had:
                    out.append(had)
                    continue
            check = radar_eccc.Check.of(scan, region) if scan is not None else None
            raw: list[np.ndarray] = []
            got = radar_eccc.draw_radar(self.net, t, type_t, region, fallback, check, raw)
            del scan
            if got is None:
                continue
            if check is not None and t == latest_t and raw:
                clutter.add(check.false_echo(raw[0]))
            amount, kind, share = filled(t, got)
            name, data = self._save_precip(
                amount, kind, f"r{t}", RADAR_SIGMA, RADAR_KIND_SIGMA, DS_RADAR, share
            )
            src = {"north": "radar-eccc", "south": "radar-eccc"}
            if check is not None:
                src["check"] = "mrms"
            key = f"{base}|{'m' if check is not None else 'n'}"
            out.append(FrameOut(t, True, name, key, "", "radar", 0, src, FINE, data, DS_RADAR, t))
            del check, got
        if not out or not p.nowcast:
            return out
        latest = max(f.t for f in out)
        type_t = radar_eccc.type_time(latest, p.types)
        types: np.ndarray | None = None
        src = {"north": "nowcast-eccc", "south": "nowcast-eccc"}
        end = max(p.nowcast)
        for t in p.nowcast:
            # How much of the forecast shows: none at the latest scan, all of it by the
            # nowcast's last frame, easing in and out between.
            w = _ease((t - latest) / max(1, end - latest))
            pair = model.pair(t) if w > 0 or seen is not None else None
            mixed = f"{w:.2f}:{pair[0].data}:{pair[1].data}" if pair else "-"
            gaps = GAPS if seen is not None else "-"
            key = (
                f"now|{FINE_KEY}|{RADAR_TYPING}|{gaps}|{p.nowcast_ref}|{t}|{type_t}|{mixed}|"
                f"{region.key}"
            )
            had = self._reusable(prev, key)
            if had:
                out.append(had)
                continue
            if types is None:
                types = radar_eccc.type_codes(self.net, type_t, region)
            got = radar_eccc.draw_nowcast(
                self.net, t, p.nowcast_ref, types, region, fallback, clutter.mask
            )
            if got is None:
                continue
            ahead = model.at(t, pair) if pair else None
            share = None
            if ahead is not None and seen is not None:
                # Blind spots first: the hand-over then fades from a filled nowcast.
                amount, kind, share = fill_gaps(got[0], got[1], ahead, seen)
                got = (amount, kind)
            if ahead is not None and w > 0:
                got = hand_over(got[0], got[1], ahead, w)
                # Where the frame is all forecast by now, nothing is "filled in".
                share = None if share is None else share * (1 - w)
            name, data = self._save_precip(
                *got, f"n{t}", RADAR_SIGMA, RADAR_KIND_SIGMA, DS_RADAR, share
            )
            out.append(
                FrameOut(t, False, name, key, "", "nowcast", 0, src, FINE, data, DS_RADAR, t)
            )
        return out

    def _coverage_path(self, region: Region) -> Path:
        """Where the radar's coverage (coverage.py) is kept, by region."""
        h = hashlib.sha1(region.key.encode()).hexdigest()[:16]
        return self.grids_dir / f"coverage-{h}.npy"

    def _clutter_path(self, region: Region) -> Path:
        """Where the radar's clutter score is kept (radar_eccc.Clutter), by region."""
        h = hashlib.sha1(region.key.encode()).hexdigest()[:16]
        return self.grids_dir / f"clutter-{h}.npy"

    def _radar_rainviewer(self, region: Region, prev: dict[str, FrameOut]) -> list[FrameOut]:
        out = []
        src = {"north": "rainviewer", "south": "rainviewer"}
        for rf in rainviewer.radar_frames(self.net):
            key = f"radar|{FINE_KEY}|{rf.path}|{region.key}"
            had = self._reusable(prev, key)
            if had:
                out.append(had)
                continue
            img = stitch(self.net, rf.template, region)
            if img is None:
                continue
            painted = repaint(img, rainviewer.radar_recolor)
            name = self._save(painted, region, f"r{rf.t}")
            # The same six steps as numbers (each step's middle), for the map to colour.
            indexed = snap(painted, region)
            numbers = dataframe.encode(_BAND_RATE[indexed], kinds_of(indexed), DS_RADAR)
            data = f"r{rf.t}-{hashlib.sha1(numbers).hexdigest()[:12]}.{dataframe.EXT}"
            self._store(data, numbers)
            out.append(
                FrameOut(rf.t, True, name, key, "", "radar", 0, src, "", data, DS_RADAR, rf.t)
            )
        return out

    # ---- Weights for the blend -------------------------------------------------------

    def _once(self, name: str, region: Region, make: Callable[[], np.ndarray]) -> np.ndarray:
        """A per-pixel weight that doesn't change within a job, worked out once."""
        key = f"{name}|{region.key}"
        with self._wlock:
            if key not in self._weights:
                self._weights[key] = make()
            return self._weights[key]

    def _domain_weight(self, name: str, region: Region, amount: np.ndarray) -> np.ndarray:
        """A source's weight from where it has data: 1 inside, fading to 0 at its edge."""
        return self._once(name, region, lambda: feather(np.isfinite(amount), feather_px(region)))

    def _south_weight(self, name: str, region: Region, amount: np.ndarray) -> np.ndarray:
        """A US model's weight in the hourly frames: its domain, south of the border."""
        return self._once(
            f"south-{name}",
            region,
            lambda: feather(np.isfinite(amount), feather_px(region)) * (1 - north_weight(region)),
        )

    def _us_weight(self, region: Region, amount: np.ndarray) -> np.ndarray:
        """NOAA's weight beyond the hourly frames and for totals: its domain, and south of
        the border (fading out between 48.5 and 49.5°N)."""
        return self._once(
            "us",
            region,
            lambda: feather(np.isfinite(amount), feather_px(region)) * (1 - north_weight(region)),
        )

    def _hrdps_weight(self, region: Region) -> np.ndarray | None:
        """HRDPS's domain weight. Its grids hold 0 outside the domain, so the domain comes
        from a picture; the last one seen is kept on disk for when GeoMet won't draw it."""
        key = f"hrdps|{region.key}"
        with self._wlock:
            if key in self._weights:
                return self._weights[key]
        path = (
            self.grids_dir
            / f"domain-hrdps-{hashlib.sha1(region.key.encode()).hexdigest()[:16]}.npy"
        )
        mask = rdps_gdps.domain_mask(self.net, HRDPS, region)
        if mask is not None and mask.any():
            save_npy(path, mask)
        else:
            try:
                mask = np.load(path)
            except (OSError, ValueError):
                return None
            if mask.shape != (region.height, region.width):
                return None
        weight = feather(mask.astype(bool), feather_px(region))
        with self._wlock:
            self._weights[key] = weight
        return weight

    def _precip(self, m: Mosaic, prefix: str, ds: int) -> tuple[str, str]:
        """Colours, once, after blending: every pixel drawn has a type."""
        wet = np.nan_to_num(m.amount, nan=0.0) >= FINE_FROM
        return self._save_precip(m.amount, fill_kinds(m.kind, wet), prefix, ds=ds)

    # ---- Forecast -----------------------------------------------------------------

    def _nbm(self, region: Region) -> Nbm | None:
        """The newest complete NBM run (once per job)."""
        if self._nbm_run is None:
            run = nbm.latest_run(self.net, int(self.now()), self.nbm_cycles)
            self._nbm_run = run if run is not None else 0
        if not self._nbm_run:
            return None
        if self._nbm_obj is None or self._nbm_obj.region != region:
            self._nbm_obj = Nbm(self.net, self._nbm_run, region, self.grib_dir, self.grids_dir)
        return self._nbm_obj

    def forecast(self, region: Region) -> dict[str, Any]:
        """The forecast timeline to 10 days, every source blended as numbers (blend.py).

        Hourly to ~48 h: HRDPS across its domain, fading over its last ~100 km into our
        HRRR (NBM's hourly fields for hours no HRRR run reaches), with RDPS filling in
        wherever neither has data. Then 3-hourly to ~84 h (RDPS) and 6-hourly to ~240 h
        (GDPS) in Canada, cross-fading across the border into NBM in the US."""
        now = int(self.now())
        prev = {f.key: f for f in self._frames_of(self._read(), region)}
        hrdps = run_of(self.net, HRDPS, HRDPS.snow)
        times = [t for t in hrdps.times if t > now] if hrdps is not None else []
        if hrdps is None or not times:
            # GeoMet didn't answer: keep the frames we have rather than blanking them.
            log.warning("no HRDPS forecast times; keeping the current forecast frames")
            return self._read()
        slots = hrrr.slots(self.net, now)
        us = self._nbm(region)
        fill = run_of(self.net, RDPS_HOURLY, RDPS_HOURLY.snow)
        # The hour just ended stays (hidden): the nowcast's hand-over reads either side of it.
        frames: list[FrameOut] = [
            f
            for f in prev.values()
            if f.kind == "forecast" and f.span_h == 1 and now - HOUR < f.t <= now
        ]
        todo: list[tuple[int, str, tuple[str, int, int] | None]] = []
        for t in times:
            south: tuple[str, int, int] | None = None
            if t in slots:
                south = ("hrrr", *slots[t])
            elif us is not None and 1 <= us.lead(t) <= nbm.HOURLY_TO_H:
                south = ("nbm", us.run, us.lead(t))
            south_key = ":".join(map(str, south)) if south else "none"
            fill_key = f"rdps:{fill.ref}" if fill is not None and t in fill.times else "none"
            key = f"fb|{FINE_KEY}|{OWNERS}|{t}|{hrdps.ref}|{south_key}|{fill_key}|{region.key}"
            had = self._reusable(prev, key)
            if had:
                frames.append(had)
            else:
                todo.append((t, key, south))

        w_hrdps = self._hrdps_weight(region) if todo else None
        if todo and w_hrdps is None:
            log.warning("no HRDPS domain picture; keeping the current forecast frames")
            return self._read()

        def draw(job: tuple[int, str, tuple[str, int, int] | None]) -> FrameOut | None:
            t, key, south = job
            assert w_hrdps is not None
            north = rdps_gdps.fields(self.net, hrdps, t, region, self.wcs_dir)
            if north is None:
                return None  # try again next time rather than keep a frame without HRDPS
            # One rule at every lead time (docs/RADAR-PLAN.md): NOAA's models in the US,
            # Canada's in Canada, cross-faded over 48.5–49.5°N; HRDPS also wherever the US
            # model has no data, and RDPS under both.
            layers: list[Layer] = []
            left: np.ndarray | float = 1.0
            kind = ""
            got: tuple[np.ndarray, np.ndarray] | None = None
            if south is not None and south[0] == "hrrr":
                got = hrrr.fields(
                    self.net, south[1], south[2], region, self.grids_dir, self.grib_dir
                )
                if got is not None:
                    kind = "hrrr"
            if not kind and us is not None and 1 <= us.lead(t) <= nbm.HOURLY_TO_H:
                got = us.precip(us.lead(t), 1)
                if got is not None:
                    kind = "nbm"
            if kind and got is not None:
                w = self._south_weight(kind, region, got[0])
                rate, k = soften(got[0], got[1], GRIB_SIGMA)
                layers.append(Layer(kind, rate, w, k))
                left = 1 - w
            layers.append(Layer("hrdps", north.rate, w_hrdps, north.kind))
            left = left * (1 - w_hrdps)
            # RDPS covers everything: it takes whatever the finer models leave.
            filled = False
            if fill is not None and t in fill.times and float(np.max(left)) > 0.02:
                under = rdps_gdps.fields(self.net, fill, t, region, self.wcs_dir)
                if under is not None:
                    layers.append(Layer("rdps", under.rate, 1.0, under.kind))
                    filled = True
            src = {"north": "hrdps", "south": kind or ("rdps" if filled else "")}
            if filled and kind:
                src["fill"] = "rdps"
            name, data = self._precip(mosaic(layers), f"f{t}", DS_HOURLY)
            valid = valid_time(t, "forecast", 1)
            return FrameOut(
                t, False, name, key, kind, "forecast", 1, src, FINE, data, DS_HOURLY, valid
            )

        if todo:
            # Two frames at a time (the sources are the slow part; more costs worker
            # memory), soonest first, with the index rewritten as they land so a first
            # build is usable early.
            with ThreadPoolExecutor(2) as pool:
                for i, frame in enumerate(pool.map(draw, todo), 1):
                    if frame is not None:
                        frames.append(frame)
                    if i % 6 == 0:
                        self._commit(region, FORECAST_KINDS, frames)
            self._commit(region, FORECAST_KINDS, frames)

        frames += self._extended(region, prev, max(times), us, frames)
        index = self._commit(region, FORECAST_KINDS, frames)
        self._prune_work()
        return index

    def _share(
        self, run: Run, t: int, block_end: int, this: np.ndarray, region: Region
    ) -> np.ndarray | float:
        """How much of NBM's 6-hour amount falls in the 3 hours ending at t, taken from how
        RDPS splits the same 6 hours (NBM has no 3-hour sums beyond 48 h). The two halves'
        shares add up to 1, so nothing is lost or counted twice; where RDPS is dry the
        split is even."""
        span = run.model.span_h * HOUR
        other_t = block_end if t < block_end else t - span
        other = (
            rdps_gdps.amount(self.net, run, run.model.precip, other_t, region, self.wcs_dir)
            if other_t in run.times
            else None
        )
        if other is None:
            return 0.5
        a, b = np.nan_to_num(this, nan=0.0), np.nan_to_num(other, nan=0.0)
        share: np.ndarray = (a + SPLIT_SOFT_MM) / (a + b + 2 * SPLIT_SOFT_MM)
        return share

    def _extended(
        self,
        region: Region,
        prev: dict[str, FrameOut],
        after: int,
        us: Nbm | None,
        done: list[FrameOut],
    ) -> list[FrameOut]:
        """3-hourly then 6-hourly frames beyond the hourly ones."""
        plan: list[tuple[int, Run]] = []
        edge = after
        for model in (RDPS, GDPS):
            run = run_of(self.net, model, model.snow)
            if run is None:
                continue
            span = model.span_h * HOUR
            for t in run.times:
                if t - span >= edge and t % span == 0:
                    plan.append((t, run))
            # End each model's stretch on a synoptic hour, where the next one's frames start.
            while plan and plan[-1][0] % (6 * HOUR):
                plan.pop()
            if plan:
                edge = plan[-1][0]
        if not plan:
            return []
        out: list[FrameOut] = []

        def job(item: tuple[int, Run]) -> FrameOut | None:
            t, run = item
            span_h = run.model.span_h
            # NBM's 6-hour block holding this frame.
            block = None
            if us is not None:
                end = -(-us.lead(t) // nbm.BLOCK_H) * nbm.BLOCK_H
                if 0 < end <= nbm.LAST_H:
                    block = end
            south_key = f"nbm:{us.run}:{block}" if us is not None and block else "none"
            key = f"fy|{FINE_KEY}|{t}|{span_h}|{run.model.name}:{run.ref}|{south_key}|{region.key}"
            had = self._reusable(prev, key)
            if had:
                return had
            north = rdps_gdps.fields(self.net, run, t, region, self.wcs_dir)
            if north is None:
                return None
            layers: list[Layer] = []
            kind = ""
            if us is not None and block:
                got = us.precip(block, nbm.BLOCK_H)
                if got is not None:
                    apcp, k = got
                    if span_h < nbm.BLOCK_H:
                        block_end = us.run + block * HOUR
                        rate = apcp * self._share(run, t, block_end, north.total, region) / span_h
                    else:
                        rate = apcp / nbm.BLOCK_H
                    rate, k = soften(rate, k, GRIB_SIGMA)
                    layers.append(Layer("nbm", rate, self._us_weight(region, apcp), k))
                    kind = "nbm"
            layers.append(Layer(run.model.name, north.rate, 1.0, north.kind))
            src = {"north": run.model.name, "south": kind or run.model.name}
            name, data = self._precip(mosaic(layers), f"f{t}", DS_EXTENDED)
            valid = valid_time(t, "forecast", span_h)
            return FrameOut(
                t, False, name, key, kind, "forecast", span_h, src, FINE, data, DS_EXTENDED, valid
            )

        with ThreadPoolExecutor(2) as pool:
            for i, frame in enumerate(pool.map(job, plan), 1):
                if frame is not None:
                    out.append(frame)
                if i % 8 == 0:
                    self._commit(region, FORECAST_KINDS, done + out)
        return out

    def _prune_work(self) -> None:
        """Drop cached downloads that haven't been used for a day."""
        grib.prune_cache(self.grib_dir)
        prune_wcs_cache(self.wcs_dir)

    # ---- Snowfall totals ------------------------------------------------------------

    def snow_totals(self, region: Region) -> dict[str, Any]:
        """Redraw the snow totals that changed and list them in the index."""
        cur = self._read()
        self._prev_totals = {t.key: t for t in self._totals_of(cur, region)}
        prev_steps = cur.get("steps") if cur.get("region") == region.key else None
        self.totals, steps = self._snow_totals(region, int(self.now()), prev_steps)
        if not self.totals and self._prev_totals:
            return self._read()  # GeoMet didn't answer: keep what we have
        index = self._commit(region, set(), None, self.totals, None, steps or {})
        self._prune_bins({t.tiles_id for t in self.totals if t.tiles_id})
        self._prune_work()
        return index

    def _steps_ok(self, steps: Any, key: str) -> bool:
        """The index's steps were drawn from these runs, and their files are there."""
        if not isinstance(steps, dict) or steps.get("key") != key:
            return False
        names = [x.get("data") for x in steps.get("steps", []) if isinstance(x, dict)]
        return bool(names) and all(isinstance(n, str) and (self.dir / n).exists() for n in names)

    def _snow_totals(
        self, region: Region, now: int, prev_steps: Any = None
    ) -> tuple[list[TotalOut], dict[str, Any] | None]:
        """Snow over the next 12 h to 10 days: Canada's models chained in Canada, NBM in
        the US, cross-faded across the border (see totals.py); and the same by elevation,
        for the terrain-adjusted map (see bins.py and terrain_totals.py). Also the same as
        numbers at every step the slider runs through (totaldata.py)."""
        hrdps = run_of(self.net, HRDPS, HRDPS.accum)
        if hrdps is None:
            return [], None
        past = [t for t in hrdps.times if t <= now]
        t0 = past[-1] if past else hrdps.times[0]
        chain = [hrdps]
        for model in (RDPS, GDPS):
            run = run_of(self.net, model, model.accum)
            if run is not None:
                chain.append(run)
        us = self._nbm(region)
        levels = terrain_totals.level_runs(self.net)
        # Windows end where both sides still have data (or where the one side does).
        last = max(r.end for r in chain)
        if us is not None:
            last = min(last, us.run + nbm.LAST_H * HOUR)
        wins = totals.window_ends(t0, last)
        step_ends = [e for _, e in totals.window_ends(t0, last, totaldata.STEP_WINDOWS)]
        runs_key = "|".join(f"{r.model.name}:{r.ref}" for r in chain)
        runs_key += f"|nbm:{us.run if us else ''}"
        runs_key += "|" + ",".join(f"{lv.name}:{lv.ref}" for lv in levels)
        steps_key = f"ts{STEPS_DRAWING}|{t0}|{runs_key}|{region.key}"
        steps_done = self._steps_ok(prev_steps, steps_key)

        out: list[TotalOut] = []
        todo: list[tuple[int, int, str]] = []
        for w, end in wins:
            key = f"tb|{w}|{t0}|{end}|{runs_key}|{region.key}"
            had = self._prev_totals.get(key)
            if had and (self.dir / had.file).exists() and self._bins_ok(had):
                out.append(had)
            else:
                todo.append((w, end, key))
        if not todo and steps_done:
            return out, prev_steps

        ends = sorted({end for _, end, _ in todo} | (set() if steps_done else set(step_ends)))
        # HRDPS only needs help from RDPS if its domain stops short of where Canada's
        # models are used (it doesn't over the default box).
        north_w = north_weight(region)
        w_hrdps = self._hrdps_weight(region)
        domain = (
            {"hrdps": w_hrdps}
            if w_hrdps is not None and bool(((w_hrdps < 0.999) & (north_w > 0)).any())
            else None
        )
        north = totals.north_totals(
            self.net, region, t0, ends, chain, self.slr_bands, self.wcs_dir, domain
        )
        south = totals.south_totals(us, t0, ends)
        used = {k: _run_ts(v) for k, v in north.runs.items()}
        us_weight: np.ndarray | float = 0.0
        made: list[TotalOut] = []
        # The steps' plain totals as codes, until their snow by elevation is ready.
        areas: dict[int, np.ndarray] = {}
        wanted_steps = set() if steps_done else set(step_ends)
        by_window = {end: (w, key) for w, end, key in todo}
        for end in ends:
            n, s = north.cm.pop(end, None), south.pop(end, None)
            if n is None and s is None:
                continue
            if s is not None:
                us_weight = self._us_weight(region, s)
            cm = totals.join(
                None if n is None else n.astype(np.float32),
                None if s is None else s.astype(np.float32),
                us_weight if s is not None else 0.0,
            )
            if end in wanted_steps:
                areas[end] = totaldata.area_plane(cm)
            if end not in by_window:
                continue
            w, key = by_window[end]
            runs = dict(used) if n is not None else {}
            if s is not None and us is not None:
                runs["nbm"] = us.run
            totals.save_grid(cm, self.totals_dir / f"{w}h.npy")
            span = round((end - t0) / HOUR)
            name = self._save(paint_total(cm), region, f"t{span}")
            made.append(TotalOut(span, t0, end, name, key, "+".join(runs), None, w, runs))
        del north, south
        written: dict[int, str] = {}

        def step_file(end: int, grid: np.ndarray | None) -> None:
            area = areas.get(end)
            if area is None or end in written:
                return
            data = totaldata.encode(area, grid)
            hours = round((end - t0) / HOUR)
            name = f"s{hours}-{hashlib.sha1(data).hexdigest()[:12]}.{totaldata.EXT}"
            self._store(name, data)
            written[end] = name

        if made or areas:
            try:
                self._snow_bins(
                    region,
                    t0,
                    made,
                    sorted(areas),
                    chain,
                    us,
                    levels,
                    w_hrdps,
                    domain,
                    us_weight,
                    step_file,
                )
            except Exception:
                log.exception("snow totals by elevation failed; the plain totals stand")
        for end in sorted(areas):
            step_file(end, None)  # no snow by elevation: the plain total alone
        steps: dict[str, Any] | None = prev_steps if steps_done else None
        if written:
            steps = {
                "start": t0,
                "key": steps_key,
                "steps": [
                    {"end": e, "hours": round((e - t0) / HOUR), "data": written[e]}
                    for e in sorted(written)
                ],
            }
        return sorted(out + made, key=lambda t: t.window), steps

    # ---- Snow totals by elevation (the terrain-adjusted map) -------------------------

    def _bins_path(self, tiles_id: str) -> Path:
        return self.totals_dir / f"bins-{tiles_id}.npy"

    def _bins_ok(self, t: TotalOut) -> bool:
        """A total from an earlier run can be kept only with its grid by elevation (one
        drawn before they existed is redrawn once)."""
        return bool(t.tiles_id) and self._bins_path(t.tiles_id).exists()

    def _snow_bins(
        self,
        region: Region,
        t0: int,
        made: list[TotalOut],
        step_ends: list[int],
        chain: list[Run],
        us: Nbm | None,
        levels: list[terrain_totals.LevelRun],
        w_hrdps: np.ndarray | None,
        domain: dict[str, np.ndarray] | None,
        us_weight: np.ndarray | float,
        on_step: Callable[[int, np.ndarray], None] | None = None,
    ) -> None:
        """The windows' snow by elevation: the US walk first (each window's grid parked
        on disk), then Canada's, joining each window as it is reached. Sets each total's
        `tiles` once its grid is written; hands each of `step_ends` to `on_step`."""
        by_end = {t.end: t for t in made}
        ends = sorted(set(by_end) | set(step_ends))
        parts = self.totals_dir / ".parts"
        parts.mkdir(parents=True, exist_ok=True)
        south_parts: dict[int, Path] = {}

        def park(end: int, acc: np.ndarray) -> None:
            path = parts / f"s-{end}.npy"
            bins.save(path, acc)
            south_parts[end] = path

        terrain_totals.south_bins(us, t0, ends, self.slr_bands, park)
        w_us = bins.half(us_weight) if isinstance(us_weight, np.ndarray) else 0.0
        meta = {"bounds": region.bounds, "width": region.width, "height": region.height}

        def finish(end: int, acc: np.ndarray | None) -> None:
            south: np.ndarray | None = None
            if end in south_parts:
                with contextlib.suppress(OSError, ValueError):
                    south = np.load(south_parts[end], mmap_mode="r")
            if acc is None and south is None:
                return
            grid = bins.join(acc, south, w_us if south is not None else 0.0)
            if on_step is not None and end in step_ends:
                on_step(end, grid)
            t = by_end.get(end)
            if t is None:
                return
            tid = hashlib.sha1(f"{t.key}|bins@{BINS_DRAWING}".encode()).hexdigest()[:16]
            bins.save(self._bins_path(tid), grid)
            write_atomic(self.totals_dir / f"bins-{tid}.json", json.dumps(meta).encode())
            t.tiles = TILES_URL.format(id=tid)
            t.tiles_id = tid

        done: set[int] = set()

        def reached(end: int, acc: np.ndarray) -> None:
            finish(end, acc)
            done.add(end)

        levels_src = terrain_totals.SnowLevels(self.net, region, levels, us, w_hrdps, self.wcs_dir)
        terrain_totals.north_bins(
            self.net,
            region,
            t0,
            ends,
            chain,
            self.slr_bands,
            levels_src,
            reached,
            self.wcs_dir,
            domain,
        )
        for end in ends:
            if end not in done:
                finish(end, None)  # Canada's chain stopped short: the US's alone
        for p in south_parts.values():
            with contextlib.suppress(OSError):
                p.unlink()

    def _prune_bins(self, keep: set[str]) -> None:
        """Drop grids by elevation (and the tiles drawn from them) that the index no
        longer uses, once they've been out of it a while."""
        cutoff = time.time() - RETIRE_S
        for p in [*self.totals_dir.glob("bins-*.npy"), *self.totals_dir.glob("bins-*.json")]:
            tid = p.stem.removeprefix("bins-")
            if tid in keep:
                continue
            with contextlib.suppress(OSError):
                if p.stat().st_mtime < cutoff:
                    p.unlink()
        tiles = self.totals_dir.parent / "snowtiles"
        for d in tiles.glob("*") if tiles.exists() else []:
            if d.name in keep or (self.totals_dir / f"bins-{d.name}.npy").exists():
                continue
            with contextlib.suppress(OSError):
                shutil.rmtree(d)


# Forecast cloud cover's look, by 5% step (0–100): clear to 5%, then from a light grey veil
# to thick grey-blue cloud, strong enough to read like the satellite's clouds over the
# light topo map and the satellite base alike.
CLOUD_FROM = 10
_cloud = np.clip((np.arange(21) * 5 - CLOUD_FROM + 5) / (100 - CLOUD_FROM + 5), 0, 1)
CLOUD_ALPHA = bytes(round(255 * (0.3 + 0.62 * f**0.8)) if f > 0 else 0 for f in _cloud)
CLOUD_RGB: list[tuple[int, int, int]] = [
    (
        round(238 - 96 * f),
        round(241 - 90 * f),
        round(245 - 78 * f),
    )
    for f in _cloud
] + [(0, 0, 0)] * (256 - 21)

# Each of the older palette's precipitation steps as a rate (mm of water an hour): its
# middle, or half as much again as its floor for a ramp's top step.
_BAND_RATE = np.zeros(256, np.float32)
for _i, (_, _low, _high) in RATE_BANDS.items():
    _BAND_RATE[_i] = float(np.sqrt(_low * _high)) if _high == _high else 1.5 * _low


def _ease(x: float) -> float:
    """0 to 1 with no corner at either end."""
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


Field = tuple[np.ndarray, np.ndarray, np.ndarray]  # rate (mm/h), snow share, mix share


class _Model:
    """The forecast frames as numbers, for the nowcast's hand-over: what the forecast
    says at any time between two of its frames."""

    def __init__(self, folder: Path, frames: list[FrameOut], region: Region) -> None:
        self.folder = folder
        self.region = region
        self.frames = sorted((f for f in frames if f.data), key=lambda f: f.valid)
        self._read: dict[str, dataframe.DataFrame | None] = {}

    def pair(self, t: int) -> tuple[FrameOut, FrameOut] | None:
        """The frames either side of t (the same one twice at either end, if it stands
        for a time within the hour)."""
        before = [f for f in self.frames if f.valid <= t]
        after = [f for f in self.frames if f.valid > t]
        a = before[-1] if before else None
        b = after[0] if after else None
        if a is None and b is not None and b.valid - t <= HOUR:
            a = b
        if b is None and a is not None and t - a.valid <= HOUR:
            b = a
        return (a, b) if a is not None and b is not None else None

    def _frame(self, f: FrameOut) -> dataframe.DataFrame | None:
        if f.data not in self._read:
            try:
                self._read[f.data] = dataframe.decode((self.folder / f.data).read_bytes())
            except OSError:
                self._read[f.data] = None
        return self._read[f.data]

    def at(self, t: int, pair: tuple[FrameOut, FrameOut]) -> Field | None:
        """The forecast at t on the region's grid, between the pair's two frames (mixed
        at their own resolution, then enlarged once)."""
        a, b = pair
        fa, fb = self._frame(a), self._frame(b)
        if fa is None or fb is None:
            return None
        f = 0.0 if a is b or b.valid <= a.valid else (t - a.valid) / (b.valid - a.valid)
        same = fa.rate.shape == fb.rate.shape and fa.snow.shape == fb.snow.shape
        if not same:
            fb, f = (fb, 1.0) if f >= 0.5 else (fa, 0.0)
        frame = dataframe.mixed(fa, fb, f) if same else fb if f else fa
        return dataframe.on_grid(frame, self.region.height, self.region.width)


def hand_over(
    amount: np.ndarray, kind: np.ndarray, ahead: Field, w: float
) -> tuple[np.ndarray, np.ndarray]:
    """A nowcast frame with `w` of the forecast for the same moment mixed in: rates as a
    straight mix, and the type whichever has more of the water behind it."""
    rate, snow, mix = ahead
    now = np.nan_to_num(amount, nan=0.0)
    out = (1 - w) * now + w * rate
    wn, wm = (1 - w) * now, w * rate
    total = wn + wm
    # Where neither is wet the type still matters (it is carried across dry ground, so an
    # edge never blends toward a wrong type): the forecast's.
    share_s = np.where(
        total > 0, (wn * (kind == SNOW_T) + wm * snow) / np.maximum(total, 1e-9), snow
    )
    share_m = np.where(total > 0, (wn * (kind == MIX_T) + wm * mix) / np.maximum(total, 1e-9), mix)
    share_r = 1 - share_s - share_m
    kinds = np.full(kind.shape, RAIN_T, np.uint8)
    kinds[(share_m >= share_r) & (share_m > share_s)] = MIX_T
    kinds[(share_s >= share_r) & (share_s >= share_m)] = SNOW_T
    return out.astype(np.float32), kinds


def fill_gaps(
    amount: np.ndarray, kind: np.ndarray, ahead: Field, seen: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A radar or nowcast frame with what radar can't see filled from the forecast for
    the same moment: where `seen` is 0 the forecast's rate, where it is 1 the radar's,
    between a part of the forecast's. The forecast only adds (an echo radar does see is
    never taken away), and where it is most of the water its type is the frame's.
    Returns the rates, the types and the share of each pixel's water filled in."""
    rate, snow, mix = ahead
    now = np.nan_to_num(amount, nan=0.0)
    add = (1 - seen) * np.maximum(0.0, rate - now)
    out = (now + add).astype(np.float32)
    share = np.zeros(out.shape, np.float32)
    np.divide(add, out, out=share, where=out > 0)
    rain = 1 - snow - mix
    model_kind = np.full(kind.shape, RAIN_T, np.uint8)
    model_kind[(mix >= rain) & (mix > snow)] = MIX_T
    model_kind[(snow >= rain) & (snow >= mix)] = SNOW_T
    take = (out > 0) & ((share >= 0.5) | (kind == NONE))
    kinds = np.where(take, model_kind, kind).astype(np.uint8)
    return out, kinds, share


def _files(index: dict[str, Any]) -> set[str]:
    """Every file an index names: frames (pictures and numbers, shown and held back for
    the hand-over), totals and the other layers' frames."""
    out = {f.get("file") for f in [*index.get("frames", []), *index.get("under", [])]}
    out |= {f.get("data") for f in [*index.get("frames", []), *index.get("under", [])]}
    out |= {t.get("file") for t in index.get("totals", [])}
    for layer in (index.get("layers") or {}).values():
        if isinstance(layer, dict):
            out |= {f.get("file") for f in layer.get("frames", [])}
            out |= {f.get("data") for f in layer.get("frames", [])}
    steps = index.get("steps")
    if isinstance(steps, dict):
        out |= {s.get("data") for s in steps.get("steps", []) if isinstance(s, dict)}
    return {n for n in out if isinstance(n, str)}
