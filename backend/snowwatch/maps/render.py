"""The map's frames: drawn into one folder and listed in `index.json` for the browser.

Three jobs share the folder, each on its own schedule (see scheduler.py):

  radar     observed radar and the nowcast, every 6 minutes
  forecast  the hourly forecast frames, every 30 minutes
  totals    the snow totals, hourly

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

from snowwatch.maps.geomet import (
    Net,
    capabilities_dims,
    geomet_map,
    on_region,
    parse_times,
    sld,
    ts_iso,
    wcs_grid,
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
    repaint,
    snap,
)
from snowwatch.maps.region import Region, stitch
from snowwatch.maps.sources import iem, radar_eccc, rainviewer, wpc

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

TOTAL_HOURS = (12, 24, 48)
SN_TOTAL_LAYER = "HRDPS.CONTINENTAL_SN"  # water equivalent (mm) since the run began

# Credit lines for the sources a frame or total came from (`src` values).
ATTRIBUTION = {
    "radar-eccc": "Radar: Environment and Climate Change Canada (North American composite)",
    "nowcast-eccc": "Nowcast: Environment and Climate Change Canada radar extrapolation",
    "rainviewer": "Radar: RainViewer",
    "hrdps": "Forecast: Environment and Climate Change Canada HRDPS",
    "hrrr-iem": "Forecast: NOAA HRRR via Iowa State University's IEM",
    "wpc": "Forecast: NOAA NWS Weather Prediction Center",
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
    # Where the US forecast came from: "hrrr", "wpc" (no type) or "" (none / radar).
    south: str
    kind: str = "forecast"  # "radar" | "nowcast" | "forecast"
    # Hours the frame's amount covers: 1 for hourly forecast frames, 0 for a rate at an
    # instant (radar, nowcast); 3 and 6 arrive with the extended forecast.
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
    hours: int
    start: int
    end: int
    file: str
    key: str
    source: str = "hrdps"
    # A terrain-adjusted tile URL template, when there is one (milestone 8).
    tiles: str | None = None

    @classmethod
    def load(cls, d: dict[str, Any]) -> TotalOut:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


class Renderer:
    """Draws frames into `out_dir` and keeps `index.json` up to date."""

    def __init__(self, out_dir: Path, net: Net, now: Callable[[], float] = time.time) -> None:
        self.dir = out_dir
        self.net = net
        self.now = now
        self.totals: list[TotalOut] = []
        self._prev_totals: dict[str, TotalOut] = {}
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
            if t.source not in srcs:
                srcs.append(t.source)
        return {
            "version": INDEX_VERSION,
            "generated": ts_iso(int(self.now())),
            "region": region.key,
            "bounds": region.bounds,
            "width": region.width,
            "height": region.height,
            "now": now,
            "frames": [asdict(f) for f in frames],
            "totals": [asdict(t) for t in sorted(totals, key=lambda t: t.hours)],
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
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
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

    def forecast(self, region: Region) -> dict[str, Any]:
        """HRDPS hourly to ~48 h, with HRRR (or WPC) outside its domain."""
        now = int(self.now())
        prev = {f.key: f for f in self._frames_of(self._read(), region)}
        dims = capabilities_dims(self.net, HRDPS_LAYERS[2][0])
        times = [t for t in parse_times(dims.get("time", "")) if t > now]
        if not times:
            # GeoMet didn't answer: keep the frames we have rather than blanking them.
            log.warning("no HRDPS forecast times; keeping the current forecast frames")
            return self._read()
        run_ref = dims.get("reference_time.default", "")
        slots = iem.hrrr_slots(self.net)
        info = wpc.wpc_info(self.net)
        frames: list[FrameOut] = []
        todo: list[tuple[int, str, int | None, int | None]] = []
        for t in times:
            minute, init = slots.get(t, (None, ""))
            layer = wpc.wpc_layer(t, info.base) if info else None
            if minute is not None:
                south_key = f"hrrr:{minute}:{init}"
            elif info and layer is not None:
                south_key = f"wpc:{layer}:{info.issued}"
            else:
                south_key = "none"
            key = f"fc|{t}|{run_ref}|{south_key}|{region.key}"
            had = self._reusable(prev, key)
            if had:
                frames.append(had)
            else:
                todo.append((t, key, minute, layer))

        if todo:
            d = geomet_map(
                self.net, DOMAIN_LAYER, sld(DOMAIN_LAYER, [(-1, "#000000")]), region, None
            )
            domain = (
                (d[..., 3] > 0) if d is not None else np.zeros((region.height, region.width), bool)
            )
            blank = np.zeros((region.height, region.width, 4), np.uint8)

            def draw(job: tuple[int, str, int | None, int | None]) -> FrameOut:
                t, key, minute, layer = job
                south, kind = blank, ""
                if minute is not None:
                    tiles = stitch(self.net, iem.tile_template(minute), region)
                    if tiles is not None:
                        south, kind = repaint(tiles, iem.hrrr_recolor), "hrrr"
                if not kind and layer is not None:
                    drawn = wpc.wpc_draw(self.net, layer, region)
                    if drawn is not None:
                        south, kind = drawn, "wpc"
                img = south.copy()
                img[domain] = 0
                for name, ramp in HRDPS_LAYERS:
                    img = over(geomet_map(self.net, name, sld(name, ramp), region, ts_iso(t)), img)
                src = {"north": "hrdps", "south": {"hrrr": "hrrr-iem"}.get(kind, kind)}
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
        return self._commit(region, FORECAST_KINDS, frames)

    # ---- Snowfall totals ------------------------------------------------------------

    def snow_totals(self, region: Region) -> dict[str, Any]:
        """Redraw the snow totals that changed and list them in the index."""
        self._prev_totals = {t.key: t for t in self._totals_of(self._read(), region)}
        self.totals = self._snow_totals(region, int(self.now()))
        if not self.totals and self._prev_totals:
            return self._read()  # GeoMet didn't answer: keep what we have
        return self._commit(region, set(), None, self.totals)

    def _snow_totals(self, region: Region, now: int) -> list[TotalOut]:
        """Snow over the next 12, 24 and 48 hours (or to the run's end), Canadian model."""
        dims = capabilities_dims(self.net, SN_TOTAL_LAYER)
        times = parse_times(dims.get("time", ""))
        if not times:
            return []
        run_ref = dims.get("reference_time.default", "")
        past = [t for t in times if t <= now]
        t0 = past[-1] if past else times[0]
        start: np.ndarray | None = None
        out: list[TotalOut] = []
        seen_ends: set[int] = set()
        for hours in TOTAL_HOURS:
            end = t0 + hours * HOUR
            if end not in times:
                end = times[-1]
            if end <= t0 or end in seen_ends:
                continue
            seen_ends.add(end)
            span = round((end - t0) / HOUR)
            key = f"tot|{run_ref}|{t0}|{end}|{region.key}"
            had = self._prev_totals.get(key)
            if had and (self.dir / had.file).exists():
                out.append(had)
                continue
            if start is None:
                g0 = wcs_grid(self.net, SN_TOTAL_LAYER, ts_iso(t0), region)
                if g0 is None:
                    return out
                start = on_region(g0, region)
            g1 = wcs_grid(self.net, SN_TOTAL_LAYER, ts_iso(end), region)
            if g1 is None:
                continue
            # mm of water over the window; at 10:1 that's cm of snow.
            cm = np.clip(on_region(g1, region) - start, 0, None)
            name = self._save(paint_total(cm), region, f"t{span}")
            out.append(TotalOut(span, t0, end, name, key, "hrdps"))
        return out
