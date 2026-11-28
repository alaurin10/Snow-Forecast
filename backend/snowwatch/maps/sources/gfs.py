"""The map past 10 days (docs/OPEN-METEO-PLAN.md, milestone 4B): NOAA's GFS at 0.25°,
from its GRIB2 files on AWS, for both countries where Canada's models (GDPS, 240 h) and
NBM (264 h) have stopped, out to 384 h.

What the files hold (probed 27 and 28 Nov 2026, the 00z runs): the 0.25° files are
3-hourly from 240 h to 384 h (`f246` … `f384`), each with an `.idx`. Past 240 h every
6-hour file has `APCP` over the 6 hours to it, `CSNOW` (categorical snow) averaged over
them, `TCDC` (entire atmosphere) averaged over them, and `TMP` at 2 m and `HGT` at the
0 °C isotherm at the hour. There's no `ASNOW` in the 0.25° files: snow water is `APCP`
× the 6-hour `CSNOW` (the share of the six hours with snow). The surface height (`HGT`
at the ground) moves the 2 m temperature to sea level like Canada's models.

A whole file is ~540 MB, so only single messages are fetched by byte range (grib.py):
`APCP` 0.37 MB, `CSNOW` 0.03 MB, `TMP` 0.87 MB, `TCDC` 0.89 MB, `HGT` 0.9 MB each, cached
on disk like NBM's. GFS is a 25 km model, so its values are put on the region's grid by
bilinear interpolation between its points (grib.on_region's nearest cell would draw
25 km squares). Days 11–16 are a rough guide, and its softness is honest.

Bucket: noaa-gfs-bdp-pds (NOAA Open Data Dissemination), free, no key.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from snowwatch.maps import grib
from snowwatch.maps.blend import kinds_from_parts
from snowwatch.maps.geomet import Net
from snowwatch.maps.region import WORLD, Region

if TYPE_CHECKING:
    from snowwatch.config import SlrBand

log = logging.getLogger("snowwatch.precip")

BUCKET = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
HOUR = 3600
LAST_H = 384
STEP_H = 6  # the 6-hour sums and averages this uses
KELVIN = 273.15


def file_url(run: int, fhour: int) -> str:
    d = datetime.fromtimestamp(run, UTC)
    return f"{BUCKET}/gfs.{d:%Y%m%d}/{d:%H}/atmos/gfs.t{d:%H}z.pgrb2.0p25.f{fhour:03d}"


def latest_run(net: Net, now: int, cycles: Iterable[int] = (0, 12)) -> int | None:
    """The newest run at one of these UTC hours whose last file is published."""
    hours = {int(c) % 24 for c in cycles}
    top = now - now % HOUR
    for back in range(0, 72):
        run = top - back * HOUR
        if datetime.fromtimestamp(run, UTC).hour not in hours:
            continue
        if net.get(file_url(run, LAST_H) + ".idx") is not None:
            return run
    return None


def block(var: str, fhour: int, kind: str) -> str:
    """The `.idx` pattern of a 6-hour sum ("acc") or average ("ave") ending at fhour."""
    return rf":{var}:surface:{fhour - STEP_H}-{fhour} hour {kind} fcst:"


# ---- On the region's grid ------------------------------------------------------------

_PIXELS: dict[str, tuple[np.ndarray, np.ndarray]] = {}


def region_lonlat(region: Region) -> tuple[np.ndarray, np.ndarray]:
    """Each region pixel's longitude and latitude (degrees), at its centre."""
    have = _PIXELS.get(region.key)
    if have is not None:
        return have
    sx = region.width / (region.x1 - region.x0)
    sy = region.height / (region.y1 - region.y0)
    x = region.x0 + (np.arange(region.width) + 0.5) / sx
    y = region.y1 - (np.arange(region.height) + 0.5) / sy
    lon = x * 180 / WORLD
    lat = np.degrees(2 * np.arctan(np.exp(y * math.pi / WORLD)) - math.pi / 2)
    out = (lon.astype(np.float64), lat.astype(np.float64))
    if len(_PIXELS) >= 4:
        _PIXELS.pop(next(iter(_PIXELS)))
    _PIXELS[region.key] = out
    return out


def regrid(values: np.ndarray, lats: np.ndarray, lons: np.ndarray, region: Region) -> np.ndarray:
    """A regular lat/lon field (rows = `lats`, columns = `lons`, the globe round in
    longitude) on the region's grid, interpolated bilinearly between its points."""
    lon, lat = region_lonlat(region)
    dlat = float(lats[1] - lats[0])
    dlon = float(lons[1] - lons[0])
    nlat, nlon = values.shape
    fi = np.clip((lat - float(lats[0])) / dlat, 0, nlat - 1)
    fj = ((lon - float(lons[0])) % 360) / dlon
    i0 = np.minimum(np.floor(fi).astype(np.int64), nlat - 2)
    j0 = np.floor(fj).astype(np.int64) % nlon
    j1 = (j0 + 1) % nlon
    wi = (fi - i0)[:, None]
    wj = (fj - np.floor(fj))[None, :]
    a = values[i0][:, j0]
    b = values[i0][:, j1]
    c = values[i0 + 1][:, j0]
    d = values[i0 + 1][:, j1]
    out: np.ndarray = ((a * (1 - wj) + b * wj) * (1 - wi) + (c * (1 - wj) + d * wj) * wi).astype(
        np.float32
    )
    return out


def on_region(raw: bytes | None, region: Region) -> np.ndarray | None:
    """One GFS message on the region's grid, or None if it's missing or unreadable."""
    if raw is None:
        return None
    try:
        values, md = grib.decode(raw)
        lats, lons = (np.asarray(a, dtype=np.float64) for a in md.latlng())
    except Exception as e:  # a bad message costs that field, not the job
        log.warning("GFS message unreadable: %s", e)
        return None
    if lats.ndim != 1 or lons.ndim != 1 or values.shape != (lats.size, lons.size):
        log.warning("GFS grid isn't a regular lat/lon grid: %s", values.shape)
        return None
    return regrid(values, lats, lons, region)


class Gfs:
    """One GFS run's fields on the region past Canada's and NBM's reach, fetched (and
    cached) as they're asked for."""

    def __init__(self, net: Net, run: int, region: Region, cache_dir: Path | None = None) -> None:
        self.net = net
        self.run = run
        self.region = region
        self.cache_dir = cache_dir
        self._ground: np.ndarray | None = None
        self._lock = threading.Lock()

    def lead(self, t: int) -> int:
        return (t - self.run) // HOUR

    def valid(self, fhour: int) -> int:
        return self.run + fhour * HOUR

    def end(self) -> int:
        return self.valid(LAST_H)

    def times(self, after: int) -> list[int]:
        """Every 6-hour time after `after` that the run reaches, on the synoptic hours."""
        return [
            t
            for fhour in range(STEP_H, LAST_H + 1, STEP_H)
            if (t := self.valid(fhour)) > after and t % (STEP_H * HOUR) == 0
        ]

    def _fields(self, fhour: int, patterns: list[str]) -> list[np.ndarray | None]:
        raw = grib.fetch_messages(self.net, file_url(self.run, fhour), patterns, self.cache_dir)
        return [on_region(m, self.region) for m in raw]

    def precip(self, t: int) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """The 6 hours to t: water (mm), the share of it as snow (0–1), and type codes;
        None if the files haven't them (t not on a 6-hour step, or past the run)."""
        fhour = self.lead(t)
        if fhour % STEP_H or not STEP_H <= fhour <= LAST_H:
            return None
        apcp, csnow = self._fields(
            fhour, [block("APCP", fhour, "acc"), block("CSNOW", fhour, "ave")]
        )
        if apcp is None:
            return None
        water = np.maximum(np.nan_to_num(apcp, nan=0.0), 0.0)
        share = np.clip(np.nan_to_num(csnow, nan=0.0) if csnow is not None else 0.0, 0.0, 1.0)
        share = np.broadcast_to(share, water.shape).astype(np.float32)
        return water, share, kinds_from_parts(water, water * share, 0.0)

    def snow_cm(self, start: int, end: int, bands: Sequence[SlrBand]) -> np.ndarray | None:
        """Snow depth (cm) between two times on 6-hour steps: each block's water × its
        share as snow × the snow ratio from the 2 m temperature at its end (the forecast's
        `slr_bands`, as totals.py does). None if a block's water is missing."""
        from snowwatch.maps.totals import ratio_grid

        total: np.ndarray | None = None
        for t in range(start + STEP_H * HOUR, end + 1, STEP_H * HOUR):
            got = self.precip(t)
            if got is None:
                return None
            water, share, _ = got
            cm = water * share * ratio_grid(self.temp_c(t), bands) / 10
            total = cm if total is None else total + cm
        return total

    def temp_c(self, t: int) -> np.ndarray | None:
        """The 2 m temperature (°C) at t, at GFS's own ground."""
        fhour = self.lead(t)
        (v,) = self._fields(fhour, [rf":TMP:2 m above ground:{fhour} hour fcst:"])
        return None if v is None else v - KELVIN

    def ground_m(self) -> np.ndarray | None:
        """GFS's surface height (m) on the region: what its 2 m temperature stands on."""
        with self._lock:
            if self._ground is None:
                (self._ground,) = self._fields(LAST_H, [rf":HGT:surface:{LAST_H} hour fcst:"])
            return self._ground

    def cloud_pct(self, t: int) -> np.ndarray | None:
        """Total cloud cover (%) averaged over the 6 hours to t."""
        fhour = self.lead(t)
        (v,) = self._fields(
            fhour, [rf":TCDC:entire atmosphere:{fhour - STEP_H}-{fhour} hour ave fcst:"]
        )
        return None if v is None else np.clip(v, 0.0, 100.0)
