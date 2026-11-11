"""Canada's models on MSC GeoMet, as numbers: HRDPS (2.5 km, to 48 h), RDPS (10 km, to
84 h) and GDPS (15 km, to 240 h).

For the forecast timeline we read each period's precipitation by type as raw grids (WCS,
mm of water over the period):

  HRDPS.CONTINENTAL.DIAG_{RN,SN,FR,PE}_PT1H                                     hourly
  RDPS_10km_{Rain,Snow}-Accum1h, RDPS_10km_{FreezingRain,IcePellets}-Accum-1h   hourly
  RDPS_10km_{Rain,Snow}-Accum3h, RDPS_10km_{FreezingRain,IcePellets}-Accum-3h   3-hourly
  GDPS_15km_{Rain,Snow}-Accum6h, GDPS_15km_{FreezingRain,IcePellets}-Accum-6h   6-hourly

(note the extra hyphen in the freezing rain and ice pellet names). The four add up to the
period's precipitation; the type comes from how it is split (blend.kinds_from_parts).
RDPS and GDPS cover all of North America. HRDPS covers Canada and the northern US, and
its grids hold 0, not "no data", outside that domain, so the domain comes from a styled
WMS picture of one of its layers (`domain_mask`).

For snow totals we read the running snow water since the run began (`…_Snow-Accum`, mm)
and the 2 m temperature (°C).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from snowwatch.maps.blend import kinds_from_parts
from snowwatch.maps.geomet import (
    Grid,
    Net,
    capabilities_dims,
    geomet_map,
    on_region,
    parse_times,
    sld,
    ts_iso,
    wcs_grid,
)
from snowwatch.maps.palette import MIX_T, RAIN_T, SNOW_T
from snowwatch.maps.region import Region

AMOUNT_RANGE = (0.0, 5000.0)


@dataclass(frozen=True)
class Model:
    name: str
    span_h: int  # hours each timeline frame covers
    rain: str
    snow: str
    freezing: str
    pellets: str
    precip: str  # all types together, over the same period
    accum: str = ""  # snow water since the run began (mm)
    temp: str = ""  # 2 m temperature (°C)


HRDPS = Model(
    "hrdps",
    1,
    "HRDPS.CONTINENTAL.DIAG_RN_PT1H",
    "HRDPS.CONTINENTAL.DIAG_SN_PT1H",
    "HRDPS.CONTINENTAL.DIAG_FR_PT1H",
    "HRDPS.CONTINENTAL.DIAG_PE_PT1H",
    "HRDPS.CONTINENTAL.DIAG_PR_PT1H",
    "HRDPS.CONTINENTAL_SN",
    "HRDPS.CONTINENTAL_TT",
)
# RDPS hour by hour: fills in wherever the finer models have nothing (it covers everything).
RDPS_HOURLY = Model(
    "rdps",
    1,
    "RDPS_10km_Rain-Accum1h",
    "RDPS_10km_Snow-Accum1h",
    "RDPS_10km_FreezingRain-Accum-1h",
    "RDPS_10km_IcePellets-Accum-1h",
    "RDPS_10km_Precip-Accum1h",
)
RDPS = Model(
    "rdps",
    3,
    "RDPS_10km_Rain-Accum3h",
    "RDPS_10km_Snow-Accum3h",
    "RDPS_10km_FreezingRain-Accum-3h",
    "RDPS_10km_IcePellets-Accum-3h",
    "RDPS_10km_Precip-Accum3h",
    "RDPS_10km_Snow-Accum",
    "RDPS_10km_AirTemp_2m",
)
GDPS = Model(
    "gdps",
    6,
    "GDPS_15km_Rain-Accum6h",
    "GDPS_15km_Snow-Accum6h",
    "GDPS_15km_FreezingRain-Accum-6h",
    "GDPS_15km_IcePellets-Accum-6h",
    "GDPS_15km_Precip-Accum6h",
    "GDPS_15km_Snow-Accum",
    "GDPS_15km_AirTemp_2m",
)


@dataclass
class Run:
    """A model run as GeoMet lists it: its start (ISO) and the times a layer has."""

    model: Model
    ref: str
    times: list[int]

    @property
    def end(self) -> int:
        return self.times[-1] if self.times else 0


def run_of(net: Net, model: Model, layer: str) -> Run | None:
    """The newest run GeoMet has for one of a model's layers. None if it doesn't answer."""
    dims = capabilities_dims(net, layer)
    times = parse_times(dims.get("time", ""))
    if not times:
        return None
    return Run(model, dims.get("reference_time.default", ""), times)


def domain_mask(net: Net, model: Model, region: Region) -> np.ndarray | None:
    """Where the model has data, from a picture of its precipitation layer drawn solid
    (its raw grids hold 0 outside the domain). None if GeoMet doesn't answer."""
    pic = geomet_map(net, model.precip, sld(model.precip, [(-1, "#000000")]), region, None)
    if pic is None:
        return None
    mask: np.ndarray = pic[..., 3] > 0
    return mask


def _grid(
    net: Net, run: Run, layer: str, t: int, region: Region, cache_dir: Path | None
) -> Grid | None:
    return wcs_grid(net, layer, ts_iso(t), region, ref=run.ref or None, cache_dir=cache_dir)


def amount(
    net: Net, run: Run, layer: str, t: int, region: Region, cache_dir: Path | None = None
) -> np.ndarray | None:
    """One layer's amount (mm) for the period ending at t, smooth on the region's grid."""
    g = _grid(net, run, layer, t, region, cache_dir)
    return None if g is None else on_region(g, region, AMOUNT_RANGE, smooth=True)


@dataclass
class Fields:
    """A period's precipitation on the region: water (mm over the period) and type."""

    total: np.ndarray
    kind: np.ndarray
    span_h: int

    @property
    def rate(self) -> np.ndarray:
        """Average mm of water an hour."""
        return self.total / self.span_h


def fields(
    net: Net, run: Run, t: int, region: Region, cache_dir: Path | None = None
) -> Fields | None:
    """The period ending at t: rain, snow, freezing rain and ice pellets added up, and the
    type from how they split. None unless both the rain and the snow grids arrive (half
    the picture would show the wrong type).

    Amounts are interpolated between the model's cells, so a 15 km model doesn't come out
    in blocks. Interpolating from a snow cell to a rain cell passes through every share
    of snow on the way, which would ring each snow area with "mix" the model never
    forecast; so mix is kept only next to a cell that is itself mixed, and elsewhere the
    line between snow and rain falls where the snow share crosses a half."""
    m = run.model
    rain = _grid(net, run, m.rain, t, region, cache_dir)
    snow = _grid(net, run, m.snow, t, region, cache_dir)
    if rain is None or snow is None or rain.data.shape != snow.data.shape:
        return None
    ice = np.zeros_like(rain.data)
    for layer in (m.freezing, m.pellets):
        part = _grid(net, run, layer, t, region, cache_dir) if layer else None
        if part is not None and part.data.shape == ice.shape:
            ice += np.nan_to_num(part.data, nan=0.0)
    total = rain.data + snow.data + ice
    mixed = kinds_from_parts(total, snow.data, ice) == MIX_T

    def smooth(values: np.ndarray) -> np.ndarray:
        g = Grid(values.astype(np.float32), rain.lon0, rain.lat0, rain.dlon, rain.dlat)
        return on_region(g, region, AMOUNT_RANGE, smooth=True)

    total_px, snow_px = smooth(total), smooth(snow.data)
    kind = kinds_from_parts(total_px, snow_px, smooth(ice))
    ring = (kind == MIX_T) & ~(np.nan_to_num(smooth(mixed), nan=0.0) > 0)
    mostly_snow = snow_px >= 0.5 * np.nan_to_num(total_px, nan=0.0)
    kind[ring & mostly_snow] = SNOW_T
    kind[ring & ~mostly_snow] = RAIN_T
    return Fields(total_px, kind, m.span_h)
