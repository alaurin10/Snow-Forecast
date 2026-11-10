"""The map's frames: drawn into one folder and listed in `index.json` for the browser.

Three jobs share the folder, each on its own schedule (see scheduler.py):

  radar     observed radar and the nowcast, every 6 minutes
  forecast  the forecast frames (hourly to 48 h, then 3- and 6-hourly to 10 days), every 30 minutes
  totals    the snow totals (12 h to 10 days), hourly

Each draws only what changed (frames are keyed by their inputs), then rewrites its own
part of the index under a file lock and leaves the other parts as they are.

Each picture's file name includes a hash of its pixels, so browsers can cache it for good.
Files that drop out of the index are kept for a quarter of an hour, so a page that loaded
the previous index can still fetch them.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import numpy as np

from snowwatch.config import SlrBand
from snowwatch.maps import grib, totals
from snowwatch.maps.files import write_atomic
from snowwatch.maps.geomet import (
    Net,
    capabilities_dims,
    geomet_map,
    iso_ts,
    parse_times,
    sld,
    ts_iso,
)
from snowwatch.maps.palette import (
    MIX,
    RAIN,
    SNOW,
    decode_indices,
    encode,
    kinds_of,
    over,
    paint_total,
    paint_typed,
    repaint,
    snap,
)
from snowwatch.maps.region import Region, stitch
from snowwatch.maps.sources import hrrr, nbm, radar_eccc, rainviewer, rdps_gdps
from snowwatch.maps.sources.nbm import Nbm
from snowwatch.maps.sources.rdps_gdps import GDPS, HRDPS, RDPS, Run, run_of

log = logging.getLogger("snowwatch.precip")

HOUR = 3600
INDEX_VERSION = 2
RETIRE_S = 15 * 60  # how long a file that left the index stays on disk

HRDPS_LAYERS = [
    ("HRDPS.CONTINENTAL.DIAG_RN_PT1H", RAIN),
    ("HRDPS.CONTINENTAL.DIAG_FR_PT1H", MIX),
    ("HRDPS.CONTINENTAL.DIAG_SN_PT1H", SNOW),
]
DOMAIN_LAYER = "HRDPS.CONTINENTAL.DIAG_PR_PT1H"
# Beyond the hourly frames, the US (NBM) and Canada (RDPS/GDPS) meet here. Milestone 2's
# last task replaces this hard join with a blend in data space (MAP-PLAN decision 8).
SEAM_LAT = 49.0

TOTAL_HOURS = totals.WINDOWS
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
    # A terrain-adjusted tile URL template, when there is one (milestone 8).
    tiles: str | None = None
    window: int = 0  # the window asked for, in hours: 12, 24, 48, 72, 120, 168, 240
    # Each model used → when its run began (Unix seconds).
    runs: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, d: dict[str, Any]) -> TotalOut:
        names = {f.name for f in fields(cls)}
        out = cls(**{k: v for k, v in d.items() if k in names})
        out.window = out.window or out.hours
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
        # Working files the browser never sees: model grid maps, cached GRIB messages,
        # and the snow totals as numbers.
        work = work_dir or out_dir / ".work"
        self.grids_dir = work / "grids"
        self.grib_dir = work / "grib"
        self.totals_dir = work / "totals"
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
    ) -> dict[str, Any]:
        """Replace the index's frames of these kinds (and the totals, if given)."""
        with self._locked():
            cur = self._read()
            old_frames = self._frames_of(cur, region)
            old_totals = self._totals_of(cur, region)
            new_frames = [f for f in old_frames if f.kind not in kinds] + (frames or [])
            new_totals = old_totals if totals is None else totals
            index = self._index(region, new_frames, new_totals)
            keep = {f["file"] for f in index["frames"]} | {t["file"] for t in index["totals"]}
            was = {f.get("file") for f in cur.get("frames", [])} | {
                t.get("file") for t in cur.get("totals", [])
            }
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
        self, region: Region, frames: list[FrameOut], totals: list[TotalOut]
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
            # More weather layers arrive with milestone 7 (snow level, wind, …).
            "layers": {},
            "attribution": [ATTRIBUTION[s] for s in srcs if s in ATTRIBUTION],
        }

    def _save(self, img: np.ndarray, region: Region, prefix: str) -> str:
        data = encode(snap(img, region))
        name = f"{prefix}-{hashlib.sha1(data).hexdigest()[:12]}.png"
        path = self.dir / name
        if path.exists():
            # Same pixels as an older file: freshen it so pruning leaves it be.
            os.utime(path)
        else:
            write_atomic(path, data)
        return name

    def _prune(self, keep: set[str]) -> None:
        """Drop pictures the index doesn't use once they've been out of it a while."""
        cutoff = time.time() - RETIRE_S
        for p in [*self.dir.glob("*.png"), *self.dir.glob("*.tmp")]:
            if p.name in keep:
                continue
            with contextlib.suppress(OSError):
                if p.stat().st_mtime < cutoff:
                    p.unlink()

    def _reusable(self, prev: dict[str, FrameOut], key: str) -> FrameOut | None:
        f = prev.get(key)
        return f if f is not None and (self.dir / f.file).exists() else None

    # ---- Everything ----------------------------------------------------------------

    def run(self, region: Region) -> dict[str, Any]:
        """Radar, forecast and totals, one after the other (`snowwatch precip`)."""
        self.radar(region)
        self.forecast(region)
        return self.snow_totals(region)

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

    # ---- Forecast -----------------------------------------------------------------

    def _nbm(self, region: Region) -> Nbm | None:
        """The newest complete NBM run (once per job)."""
        if self._nbm_run is None:
            run = nbm.latest_run(self.net, int(self.now()), self.nbm_cycles)
            self._nbm_run = run if run is not None else 0
        if not self._nbm_run:
            return None
        return Nbm(self.net, self._nbm_run, region, self.grib_dir, self.grids_dir)

    def forecast(self, region: Region) -> dict[str, Any]:
        """The forecast timeline to 10 days.

        Hourly to ~48 h: HRDPS where its domain covers, our HRRR elsewhere (NBM's hourly
        fields for hours no HRRR run reaches). Then 3-hourly to ~84 h (RDPS north of 49°N)
        and 6-hourly to ~240 h (GDPS), with NBM south of 49°N."""
        now = int(self.now())
        prev = {f.key: f for f in self._frames_of(self._read(), region)}
        dims = capabilities_dims(self.net, HRDPS_LAYERS[2][0])
        times = [t for t in parse_times(dims.get("time", "")) if t > now]
        if not times:
            # GeoMet didn't answer: keep the frames we have rather than blanking them.
            log.warning("no HRDPS forecast times; keeping the current forecast frames")
            return self._read()
        run_ref = dims.get("reference_time.default", "")
        slots = hrrr.slots(self.net, now)
        blend = self._nbm(region)
        frames: list[FrameOut] = []
        todo: list[tuple[int, str, tuple[str, int, int] | None]] = []
        for t in times:
            south: tuple[str, int, int] | None = None
            if t in slots:
                south = ("hrrr", *slots[t])
            elif blend is not None and 1 <= blend.lead(t) <= nbm.HOURLY_TO_H:
                south = ("nbm", blend.run, blend.lead(t))
            south_key = ":".join(map(str, south)) if south else "none"
            key = f"fc|{t}|{run_ref}|{south_key}|{region.key}"
            had = self._reusable(prev, key)
            if had:
                frames.append(had)
            else:
                todo.append((t, key, south))

        if todo:
            d = geomet_map(
                self.net, DOMAIN_LAYER, sld(DOMAIN_LAYER, [(-1, "#000000")]), region, None
            )
            domain = (
                (d[..., 3] > 0) if d is not None else np.zeros((region.height, region.width), bool)
            )
            blank = np.zeros((region.height, region.width, 4), np.uint8)

            def draw(job: tuple[int, str, tuple[str, int, int] | None]) -> FrameOut:
                t, key, south = job
                pic, kind = None, ""
                if south and south[0] == "hrrr":
                    pic = hrrr.draw(self.net, south[1], south[2], region, self.grids_dir)
                    kind = "hrrr" if pic is not None else ""
                if pic is None and blend is not None and 1 <= blend.lead(t) <= nbm.HOURLY_TO_H:
                    pic = blend.draw(blend.lead(t), 1)
                    kind = "nbm" if pic is not None else ""
                img = (pic if pic is not None else blank).copy()
                img[domain] = 0
                for name, ramp in HRDPS_LAYERS:
                    img = over(geomet_map(self.net, name, sld(name, ramp), region, ts_iso(t)), img)
                src = {"north": "hrdps", "south": kind}
                name = self._save(img, region, f"f{t}")
                return FrameOut(t, False, name, key, kind, "forecast", 1, src)

            # Two frames at a time (the sources are the slow part; more costs worker
            # memory), soonest first, with the index rewritten as they land so a first
            # build is usable early.
            with ThreadPoolExecutor(2) as pool:
                for i, frame in enumerate(pool.map(draw, todo), 1):
                    frames.append(frame)
                    if i % 6 == 0:
                        self._commit(region, FORECAST_KINDS, frames)
            self._commit(region, FORECAST_KINDS, frames)

        frames += self._extended(region, prev, max(times), blend, frames)
        return self._commit(region, FORECAST_KINDS, frames)

    def _extended(
        self,
        region: Region,
        prev: dict[str, FrameOut],
        after: int,
        blend: Nbm | None,
        done: list[FrameOut],
    ) -> list[FrameOut]:
        """3-hourly then 6-hourly frames beyond the hourly ones."""
        plan: list[tuple[int, Run]] = []
        edge = after
        for model, layer in ((RDPS, RDPS.snow), (GDPS, GDPS.snow)):
            run = run_of(self.net, model, layer)
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
        lats = region.lonlats()[1]
        south_rows = (lats < SEAM_LAT)[:, None]
        out: list[FrameOut] = []

        def job(item: tuple[int, Run]) -> FrameOut | None:
            t, run = item
            span_h = run.model.span_h
            # NBM's 6-hour block holding this frame (a 3-hour frame shows its block's average).
            block = None
            if blend is not None:
                lead = blend.lead(t)
                end = -(-lead // nbm.BLOCK_H) * nbm.BLOCK_H
                if nbm.HOURLY_TO_H < end <= nbm.LAST_H:
                    block = end
            south_key = f"nbm:{blend.run}:{block}" if blend is not None and block else "none"
            key = f"fx|{t}|{span_h}|{run.model.name}:{run.ref}|{south_key}|{region.key}"
            had = self._reusable(prev, key)
            if had:
                return had
            north = rdps_gdps.draw(self.net, run, t, region)
            if north is None:
                return None
            img = north
            kind = ""
            if blend is not None and block:
                got = blend.precip(block, nbm.BLOCK_H)
                if got is not None:
                    apcp, k = got
                    south = paint_typed(apcp / nbm.BLOCK_H, k)
                    take = south_rows & np.isfinite(apcp)
                    img = north.copy()
                    img[take] = south[take]
                    kind = "nbm"
            src = {"north": run.model.name, "south": kind or run.model.name}
            name = self._save(img, region, f"f{t}")
            return FrameOut(t, False, name, key, kind, "forecast", span_h, src)

        with ThreadPoolExecutor(2) as pool:
            for i, frame in enumerate(pool.map(job, plan), 1):
                if frame is not None:
                    out.append(frame)
                if i % 8 == 0:
                    self._commit(region, FORECAST_KINDS, done + out)
        return out

    # ---- Snowfall totals ------------------------------------------------------------

    def snow_totals(self, region: Region) -> dict[str, Any]:
        """Redraw the snow totals that changed and list them in the index."""
        self._prev_totals = {t.key: t for t in self._totals_of(self._read(), region)}
        self.totals = self._snow_totals(region, int(self.now()))
        if not self.totals and self._prev_totals:
            return self._read()  # GeoMet didn't answer: keep what we have
        index = self._commit(region, set(), None, self.totals)
        grib.prune_cache(self.grib_dir)
        return index

    def _snow_totals(self, region: Region, now: int) -> list[TotalOut]:
        """Snow over the next 12 h to 10 days: Canada's models chained north of the seam,
        NBM south of it (see totals.py)."""
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
        blend = self._nbm(region)
        # Windows end where both sides still have data (or where the one side does).
        last = max(r.end for r in chain)
        if blend is not None:
            last = min(last, blend.run + nbm.LAST_H * HOUR)
        wins = totals.window_ends(t0, last)
        runs_key = "|".join(f"{r.model.name}:{r.ref}" for r in chain)
        runs_key += f"|nbm:{blend.run if blend else ''}"

        out: list[TotalOut] = []
        todo: list[tuple[int, int, str]] = []
        for w, end in wins:
            key = f"tot|{w}|{t0}|{end}|{runs_key}|{region.key}"
            had = self._prev_totals.get(key)
            if had and (self.dir / had.file).exists():
                out.append(had)
            else:
                todo.append((w, end, key))
        if not todo:
            return out

        ends = [end for _, end, _ in todo]
        north = totals.north_totals(self.net, region, t0, ends, chain, self.slr_bands)
        south = totals.south_totals(blend, t0, ends)
        weight = totals.seam_weight(region)
        used = {k: _run_ts(v) for k, v in north.runs.items()}
        for w, end, key in todo:
            n, s = north.cm.get(end), south.get(end)
            if n is None and s is None:
                continue
            cm = totals.blend(n, s, weight)
            runs = {k: v for k, v in used.items() if n is not None}
            if s is not None and blend is not None:
                runs["nbm"] = blend.run
            totals.save_grid(cm, self.totals_dir / f"{w}h.npy")
            span = round((end - t0) / HOUR)
            name = self._save(paint_total(cm), region, f"t{span}")
            out.append(TotalOut(span, t0, end, name, key, "+".join(runs), None, w, runs))
        return sorted(out, key=lambda t: t.window)
