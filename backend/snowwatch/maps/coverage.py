"""Where the radar sees, so its blind spots can be filled from the forecast
(docs/RADAR-PLAN.md M3).

In the mountains radar misses a lot: a ridge blocks the beam (the spokes behind it), and
far from a radar the beam passes kilometres above a valley floor, over snow falling from
low cloud. Such places show as dry. Where no radar sees well, render.py fills the radar
and nowcast frames from the forecast for the same moment, and the map draws that part
lighter and hatched.

  - MRMS's radar quality index (NOAA; US and southern Canada to 55°N, Canada's radars
    included): beam blockage and beam height. Seen fully at 0.5 and above, blind at 0.15
    and below, in between a ramp.
  - Environment Canada's coverage (`RADAR_COVERAGE_RRAI.INV`, the area no radar reaches,
    updated as radars go down): north of MRMS and out to sea.

The result is `seen`: 1 where radar sees, 0 where it is blind, softened over a few km so
the fill has no edge. It changes slowly (a radar going down), so it is worked out at most
every COVERAGE_EVERY_S and kept on disk: if both sources fail, the last one serves.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from pathlib import Path

import numpy as np

from snowwatch.maps.files import save_npy
from snowwatch.maps.geomet import Net, geomet_map
from snowwatch.maps.region import Region
from snowwatch.maps.smooth import blur
from snowwatch.maps.sources import mrms

log = logging.getLogger("snowwatch.precip")

QUALITY_BLIND = 0.15
QUALITY_SEEN = 0.5
UNCOVERED_LAYER = "RADAR_COVERAGE_RRAI.INV"
COVERAGE_EVERY_S = 30 * 60
RETRY_S = 10 * 60  # after neither source answered
KEEP_S = 24 * 3600  # an older map on disk is not used
SOFTEN_PX = 2.0


def from_quality(q: np.ndarray) -> np.ndarray:
    """MRMS's quality index (0..1, NaN outside its grid) to `seen` (NaN outside)."""
    x = np.clip((q - QUALITY_BLIND) / (QUALITY_SEEN - QUALITY_BLIND), 0.0, 1.0)
    out: np.ndarray = (x * x * (3 - 2 * x)).astype(np.float32)
    return out


def from_mask(img: np.ndarray) -> np.ndarray:
    """GeoMet's picture of the area no radar reaches (grey where uncovered) to `seen`."""
    out: np.ndarray = (img[..., 3] < 32).astype(np.float32)
    return out


def combine(quality: np.ndarray | None, mask: np.ndarray | None) -> np.ndarray | None:
    """MRMS where it reaches, GeoMet's coverage beyond (or both missing: None). Without
    GeoMet's, beyond MRMS counts as seen (no fill rather than a wrong one)."""
    if quality is None and mask is None:
        return None
    shape = (quality if quality is not None else mask).shape  # type: ignore[union-attr]
    seen = mask.copy() if mask is not None else np.ones(shape, np.float32)
    if quality is not None:
        inside = np.isfinite(quality)
        seen[inside] = from_quality(quality[inside])
    soft: np.ndarray = 1 - blur(1 - seen, SOFTEN_PX)
    return np.clip(soft, 0.0, 1.0).astype(np.float32)


class Coverage:
    """`seen` for one region, worked out now and then and kept at `path`."""

    def __init__(self, path: Path, region: Region, now: float | None = None) -> None:
        self.path = path
        self.region = region
        self.now = time.time() if now is None else now

    def _kept(self, max_age: float) -> np.ndarray | None:
        try:
            if self.now - self.path.stat().st_mtime > max_age:
                return None
            got = np.load(self.path)
        except (OSError, ValueError):
            return None
        return got if got.shape == (self.region.height, self.region.width) else None

    def get(self, net: Net, t: int) -> np.ndarray | None:
        """`seen` near time t: the kept one if it's recent, else worked out again (and
        the kept one, up to a day old, if neither source answers)."""
        fresh = self._kept(COVERAGE_EVERY_S)
        if fresh is not None:
            return fresh
        tried = self.path.with_suffix(".tried")
        with contextlib.suppress(OSError):
            if self.now - tried.stat().st_mtime < RETRY_S:
                return self._kept(KEEP_S)
        quality = mrms.quality(net, t, self.region)
        img = geomet_map(net, UNCOVERED_LAYER, None, self.region, None)
        mask = from_mask(img) if img is not None and img.ndim == 3 else None
        seen = combine(quality, mask)
        if seen is None:
            log.warning("radar coverage: neither MRMS nor GeoMet answered")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tried.touch()
            os.utime(tried, (self.now, self.now))
            return self._kept(KEEP_S)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        save_npy(self.path, seen)
        # Its age is judged by the renderer's clock.
        os.utime(self.path, (self.now, self.now))
        return seen
