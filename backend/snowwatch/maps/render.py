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
from snowwatch.maps import bins, grib, terrain_totals, totals
from snowwatch.maps.blend import (
    WET_MM,
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
    decode_indices,
    encode,
    index_ramp,
    kinds_of,
    paint_total,
    paint_typed,
    repaint,
    snap,
)
from snowwatch.maps.point import PROBE_STEP
from snowwatch.maps.region import Region, stitch
from snowwatch.maps.sources import hrrr, nbm, radar_eccc, rainviewer, rdps_gdps
from snowwatch.maps.sources.nbm import Nbm
from snowwatch.maps.sources.rdps_gdps import GDPS, HRDPS, RDPS, RDPS_HOURLY, Run, run_of

log = logging.getLogger("snowwatch.precip")

HOUR = 3600
INDEX_VERSION = 2
RETIRE_S = 15 * 60  # how long a file that left the index stays on disk

DOMAIN_LAYER = HRDPS.precip  # drawn solid, it shows where HRDPS has data
# Splitting NBM's 6-hour amount between two 3-hour frames follows RDPS's split, softened
# by this much water (mm) so a trace in one half doesn't take everything.
SPLIT_SOFT_MM = 0.25

TOTAL_HOURS = totals.WINDOWS
# Part of every grid by elevation's name: change it when how they're built changes.
BINS_DRAWING = 1
TILES_URL = "/api/snowtiles/{id}/{{z}}/{{x}}/{{y}}.png"
SN_TOTAL_LAYER = HRDPS.accum  # water equivalent (mm) since the run began

# Credit lines for the sources a frame or total came from (`src` values).
ATTRIBUTION = {
    "radar-eccc": "Radar: Environment and Climate Change Canada (North American composite)",
    "nowcast-eccc": "Nowcast: Environment and Climate Change Canada radar extrapolation",
    "rainviewer": "Radar: RainViewer",
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

    @classmethod
    def load(cls, d: dict[str, Any]) -> FrameOut:
        """From the index, including one written before v2."""
        d = dict(d)
        d.setdefault("kind", "radar" if d.get("past") else "forecast")
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


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

    @classmethod
    def load(cls, d: dict[str, Any]) -> LayerFrame:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def probe_sample(values: np.ndarray) -> np.ndarray:
    """Every PROBE_STEP-th pixel each way, from the middle of each block (the last two
    axes: rows, columns)."""
    k = PROBE_STEP // 2
    out: np.ndarray = values[..., k::PROBE_STEP, k::PROBE_STEP]
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
    ) -> None:
        self.dir = out_dir
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
        for f in index.get("frames", []):
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
    ) -> dict[str, Any]:
        """Replace the index's frames of these kinds (and the totals, and the named
        layers, if given)."""
        with self._locked():
            cur = self._read()
            old_frames = self._frames_of(cur, region)
            old_totals = self._totals_of(cur, region)
            new_frames = [f for f in old_frames if f.kind not in kinds] + (frames or [])
            new_totals = old_totals if totals is None else totals
            new_layers = {**self._layers_of(cur, region), **(layers or {})}
            index = self._index(region, new_frames, new_totals, new_layers)
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
    ) -> dict[str, Any]:
        now = max((f.t for f in frames if f.kind == "radar"), default=None)
        if now is not None:
            # A forecast hour that ended before the latest radar scan is over.
            frames = [f for f in frames if f.kind == "radar" or f.t > now]
        frames = sorted(frames, key=lambda f: (f.t, f.kind != "radar"))
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
            "totals": [asdict(t) for t in sorted(totals, key=lambda t: (t.window, t.hours))],
            "layers": {k: {"frames": [asdict(f) for f in v]} for k, v in layers.items()},
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
            self._write_probe(name, probe_sample(indexed))
        else:
            self._write_probe(name, probe_sample(values).astype(np.float16))
        return name

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
        self._write_probe(name, probe_sample(keep).astype(np.float16))
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
        if not self._probe_path(f.file).exists():
            # Drawn before probes existed: make its probe from the picture.
            try:
                idx = decode_indices((self.dir / f.file).read_bytes())
            except OSError:
                idx = None
            if idx is not None:
                self._write_probe(f.file, probe_sample(idx))
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
        return None if idx is None else kinds_of(idx)

    def radar(self, region: Region) -> dict[str, Any]:
        """Observed radar for the last 3 hours and the next 72 minutes' nowcast."""
        old = self._frames_of(self._read(), region)
        prev = {f.key: f for f in old}
        frames = self._radar_eccc(region, prev, self._forecast_types(old))
        if not any(f.kind == "radar" for f in frames):
            log.warning("Environment Canada radar returned nothing; using RainViewer")
            frames = self._radar_rainviewer(region, prev)
        return self._commit(region, RADAR_KINDS, frames)

    def _radar_eccc(
        self, region: Region, prev: dict[str, FrameOut], fallback: np.ndarray | None
    ) -> list[FrameOut]:
        p = radar_eccc.plan(self.net)
        if p is None:
            return []
        out: list[FrameOut] = []
        src = {"north": "radar-eccc", "south": "radar-eccc"}
        for t in p.radar:
            type_t = radar_eccc.type_time(t, p.types)
            key = f"eccc|{t}|{type_t}|{region.key}"
            had = self._reusable(prev, key)
            if had:
                out.append(had)
                continue
            img = radar_eccc.draw_radar(self.net, t, type_t, region, fallback)
            if img is None:
                continue
            out.append(
                FrameOut(t, True, self._save(img, region, f"r{t}"), key, "", "radar", 0, src)
            )
        if not out or not p.nowcast:
            return out
        latest = max(f.t for f in out)
        type_t = radar_eccc.type_time(latest, p.types)
        types: np.ndarray | None = None
        src = {"north": "nowcast-eccc", "south": "nowcast-eccc"}
        for t in p.nowcast:
            key = f"now|{p.nowcast_ref}|{t}|{type_t}|{region.key}"
            had = self._reusable(prev, key)
            if had:
                out.append(had)
                continue
            if types is None:
                types = radar_eccc.type_codes(self.net, type_t, region)
            img = radar_eccc.draw_nowcast(self.net, t, p.nowcast_ref, types, region, fallback)
            if img is None:
                continue
            out.append(
                FrameOut(t, False, self._save(img, region, f"n{t}"), key, "", "nowcast", 0, src)
            )
        return out

    def _radar_rainviewer(self, region: Region, prev: dict[str, FrameOut]) -> list[FrameOut]:
        out = []
        src = {"north": "rainviewer", "south": "rainviewer"}
        for rf in rainviewer.radar_frames(self.net):
            key = f"radar|{rf.path}|{region.key}"
            had = self._reusable(prev, key)
            if had:
                out.append(had)
                continue
            img = stitch(self.net, rf.template, region)
            if img is None:
                continue
            painted = repaint(img, rainviewer.radar_recolor)
            name = self._save(painted, region, f"r{rf.t}")
            out.append(FrameOut(rf.t, True, name, key, "", "radar", 0, src))
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

    @staticmethod
    def _paint(m: Mosaic) -> np.ndarray:
        """Colours, once, after blending."""
        wet = np.nan_to_num(m.amount, nan=0.0) >= WET_MM
        return paint_typed(m.amount, fill_kinds(m.kind, wet))

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
        frames: list[FrameOut] = []
        todo: list[tuple[int, str, tuple[str, int, int] | None]] = []
        for t in times:
            south: tuple[str, int, int] | None = None
            if t in slots:
                south = ("hrrr", *slots[t])
            elif us is not None and 1 <= us.lead(t) <= nbm.HOURLY_TO_H:
                south = ("nbm", us.run, us.lead(t))
            south_key = ":".join(map(str, south)) if south else "none"
            fill_key = f"rdps:{fill.ref}" if fill is not None and t in fill.times else "none"
            key = f"fb|{t}|{hrdps.ref}|{south_key}|{fill_key}|{region.key}"
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
            layers = [Layer("hrdps", north.rate, w_hrdps, north.kind)]
            left = 1 - w_hrdps
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
                w = self._domain_weight(kind, region, got[0])
                layers.append(Layer(kind, got[0], w, got[1]))
                left = left * (1 - w)
            # RDPS covers everything: it takes whatever the finer models leave.
            filled = False
            if fill is not None and t in fill.times and float(left.max()) > 0.02:
                under = rdps_gdps.fields(self.net, fill, t, region, self.wcs_dir)
                if under is not None:
                    layers.append(Layer("rdps", under.rate, 1.0, under.kind))
                    filled = True
            src = {"north": "hrdps", "south": kind or ("rdps" if filled else "")}
            if filled and kind:
                src["fill"] = "rdps"
            name = self._save(self._paint(mosaic(layers)), region, f"f{t}")
            return FrameOut(t, False, name, key, kind, "forecast", 1, src)

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
            key = f"fy|{t}|{span_h}|{run.model.name}:{run.ref}|{south_key}|{region.key}"
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
                    layers.append(Layer("nbm", rate, self._us_weight(region, apcp), k))
                    kind = "nbm"
            layers.append(Layer(run.model.name, north.rate, 1.0, north.kind))
            src = {"north": run.model.name, "south": kind or run.model.name}
            name = self._save(self._paint(mosaic(layers)), region, f"f{t}")
            return FrameOut(t, False, name, key, kind, "forecast", span_h, src)

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
        self._prev_totals = {t.key: t for t in self._totals_of(self._read(), region)}
        self.totals = self._snow_totals(region, int(self.now()))
        if not self.totals and self._prev_totals:
            return self._read()  # GeoMet didn't answer: keep what we have
        index = self._commit(region, set(), None, self.totals)
        self._prune_bins({t.tiles_id for t in self.totals if t.tiles_id})
        self._prune_work()
        return index

    def _snow_totals(self, region: Region, now: int) -> list[TotalOut]:
        """Snow over the next 12 h to 10 days: Canada's models chained in Canada, NBM in
        the US, cross-faded across the border (see totals.py); and the same by elevation,
        for the terrain-adjusted map (see bins.py and terrain_totals.py)."""
        hrdps = run_of(self.net, HRDPS, HRDPS.accum)
        if hrdps is None:
            return []
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
        runs_key = "|".join(f"{r.model.name}:{r.ref}" for r in chain)
        runs_key += f"|nbm:{us.run if us else ''}"
        runs_key += "|" + ",".join(f"{lv.name}:{lv.ref}" for lv in levels)

        out: list[TotalOut] = []
        todo: list[tuple[int, int, str]] = []
        for w, end in wins:
            key = f"tb|{w}|{t0}|{end}|{runs_key}|{region.key}"
            had = self._prev_totals.get(key)
            if had and (self.dir / had.file).exists() and self._bins_ok(had):
                out.append(had)
            else:
                todo.append((w, end, key))
        if not todo:
            return out

        ends = [end for _, end, _ in todo]
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
        for w, end, key in todo:
            n, s = north.cm.get(end), south.get(end)
            if n is None and s is None:
                continue
            if s is not None:
                us_weight = self._us_weight(region, s)
            cm = totals.join(n, s, us_weight if s is not None else 0.0)
            runs = dict(used) if n is not None else {}
            if s is not None and us is not None:
                runs["nbm"] = us.run
            totals.save_grid(cm, self.totals_dir / f"{w}h.npy")
            span = round((end - t0) / HOUR)
            name = self._save(paint_total(cm), region, f"t{span}")
            made.append(TotalOut(span, t0, end, name, key, "+".join(runs), None, w, runs))
        del north, south  # (a picture-sized grid per window each side)
        if made:
            try:
                self._snow_bins(region, t0, made, chain, us, levels, w_hrdps, domain, us_weight)
            except Exception:
                log.exception("snow totals by elevation failed; the plain totals stand")
        return sorted(out + made, key=lambda t: t.window)

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
        chain: list[Run],
        us: Nbm | None,
        levels: list[terrain_totals.LevelRun],
        w_hrdps: np.ndarray | None,
        domain: dict[str, np.ndarray] | None,
        us_weight: np.ndarray | float,
    ) -> None:
        """The windows' snow by elevation: the US walk first (each window's grid parked
        on disk), then Canada's, joining each window as it is reached. Sets each total's
        `tiles` once its grid is written."""
        by_end = {t.end: t for t in made}
        ends = sorted(by_end)
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
            t = by_end[end]
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


def _files(index: dict[str, Any]) -> set[str]:
    """Every picture an index names: frames, totals and the other layers' frames."""
    out = {f.get("file") for f in index.get("frames", [])}
    out |= {t.get("file") for t in index.get("totals", [])}
    for layer in (index.get("layers") or {}).values():
        if isinstance(layer, dict):
            out |= {f.get("file") for f in layer.get("frames", [])}
    return {n for n in out if isinstance(n, str)}
