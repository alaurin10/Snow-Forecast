"""Canada's longer-range models on MSC GeoMet: RDPS (10 km, to 84 h) and GDPS (15 km, to 240 h).

Both cover all of North America. For the forecast timeline we draw their accumulations by
type as styled pictures, the same way as HRDPS:

  RDPS_10km_{Rain,Snow}-Accum3h, RDPS_10km_{FreezingRain,IcePellets}-Accum-3h   3-hourly
  GDPS_15km_{Rain,Snow}-Accum6h, GDPS_15km_{FreezingRain,IcePellets}-Accum-6h   6-hourly

(note the extra hyphen in the freezing rain and ice pellet names). Our SLD multiplies the
ramp's bounds by the period's hours, so colours still mean an hourly rate.

For snow totals we read the running snow water since the run began (`…_Snow-Accum`, mm)
and the 2 m temperature (°C) as raw grids (WCS).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from snowwatch.maps.geomet import Net, capabilities_dims, geomet_map, parse_times, sld, ts_iso
from snowwatch.maps.palette import MIX, RAIN, SNOW, over
from snowwatch.maps.region import Region


@dataclass(frozen=True)
class Model:
    name: str
    span_h: int  # hours each timeline frame covers
    rain: str
    snow: str
    freezing: str
    pellets: str
    accum: str  # snow water since the run began (mm)
    temp: str  # 2 m temperature (°C)


HRDPS = Model(
    "hrdps",
    1,
    "HRDPS.CONTINENTAL.DIAG_RN_PT1H",
    "HRDPS.CONTINENTAL.DIAG_SN_PT1H",
    "HRDPS.CONTINENTAL.DIAG_FR_PT1H",
    "",
    "HRDPS.CONTINENTAL_SN",
    "HRDPS.CONTINENTAL_TT",
)
RDPS = Model(
    "rdps",
    3,
    "RDPS_10km_Rain-Accum3h",
    "RDPS_10km_Snow-Accum3h",
    "RDPS_10km_FreezingRain-Accum-3h",
    "RDPS_10km_IcePellets-Accum-3h",
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


def draw(net: Net, run: Run, t: int, region: Region) -> np.ndarray | None:
    """The period ending at t, by type: rain, then mix (freezing rain, ice pellets), then
    snow on top. None if GeoMet sent no picture at all."""
    m = run.model
    extra = {"dim_reference_time": run.ref} if run.ref else None
    layers = [(m.rain, RAIN), (m.pellets, MIX), (m.freezing, MIX), (m.snow, SNOW)]
    img: np.ndarray | None = None
    for layer, ramp in layers:
        if not layer:
            continue
        pic = geomet_map(net, layer, sld(layer, ramp, m.span_h), region, ts_iso(t), extra)
        if pic is None:
            continue
        img = pic if img is None else over(pic, img)
    return img
