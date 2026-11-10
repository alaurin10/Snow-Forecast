"""Fallback radar: RainViewer's free mosaic (zoom 7, about 2 h of history).

Its published "Universal Blue" table (rainviewer.com/api/color-schemes.html) gives each
colour's dBZ and whether it's rain or snow; we turn that into a rate on our ramps.
Used only when Environment Canada's radar returns nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from snowwatch.maps.geomet import Net
from snowwatch.maps.palette import RAIN, RGB, SNOW, hex_rgb, ramp_color

RAINVIEWER_INDEX = "https://api.rainviewer.com/public/weather-maps.json"

RV_RAIN_FROM = 15
RV_RAIN = [
    "88ddee",
    "6cd1eb",
    "51c5e8",
    "36bae5",
    "1baee2",
    "00a3e0",
    "009ad5",
    "0091ca",
    "0088bf",
    "007fb4",
    "0077aa",
    "0070a3",
    "00699c",
    "006295",
    "005b8e",
    "005588",
    "005180",
    "004e78",
    "004a70",
    "004768",
    "ffee00",
    "ffe000",
    "ffd200",
    "ffc500",
    "ffb700",
    "ffaa00",
    "ff9f00",
    "ff9500",
    "ff8b00",
    "ff8100",
    "ff4400",
    "f23600",
    "e62800",
    "d91b00",
    "cd0d00",
    "c10000",
    "a80000",
    "8f0000",
    "760000",
    "5d0000",
    "ffaaff",
    "ff9fff",
    "ff95ff",
    "ff8bff",
    "ff81ff",
    "ff77ff",
    "ff6cff",
    "ff62ff",
    "ff58ff",
    "ff4eff",
]
RV_SNOW_FROM = 0
RV_SNOW = [
    "c7ffff",
    "c6ffff",
    "c5ffff",
    "c4ffff",
    "c3ffff",
    "c3ffff",
    "c2ffff",
    "c1ffff",
    "c0ffff",
    "bfffff",
    "bfffff",
    "b8f8ff",
    "b2f2ff",
    "abebff",
    "a5e5ff",
    "9fdfff",
    "98d8ff",
    "92d2ff",
    "8bcbff",
    "85c5ff",
    "7fbfff",
    "78b8ff",
    "72b2ff",
    "6babff",
    "65a5ff",
    "5f9fff",
    "5b9bff",
    "5898ff",
    "5595ff",
    "5292ff",
    "4f8fff",
    "4b8bff",
    "4888ff",
    "4585ff",
    "4282ff",
    "3f7fff",
    "3b7bff",
    "3878ff",
    "3575ff",
    "3272ff",
    "2f6fff",
    "2b6bff",
    "2868ff",
    "2565ff",
    "2262ff",
    "1f5fff",
    "1b5bff",
    "1858ff",
    "1555ff",
    "1252ff",
    "0f4fff",
    "0c4bff",
    "0948ff",
    "0645ff",
    "0242ff",
    "003fff",
    "003bff",
    "0038ff",
    "0035ff",
    "0032ff",
]
_RV = [(hex_rgb("#" + h), False, RV_RAIN_FROM + i) for i, h in enumerate(RV_RAIN)] + [
    (hex_rgb("#" + h), True, RV_SNOW_FROM + i) for i, h in enumerate(RV_SNOW)
]


def rain_rate(dbz: float) -> float:
    """Marshall–Palmer, Z = 200 R^1.6, mm/h."""
    return float((10 ** (dbz / 10) / 200) ** (1 / 1.6))


def snow_rate(dbz: float) -> float:
    """Z = 180 S^2 (NEXRAD's cautious snow setting), mm of water/h ≈ cm of snow/h."""
    return math.sqrt(10 ** (dbz / 10) / 180)


def radar_recolor(r: int, g: int, b: int) -> RGB | None:
    best, dist = _RV[0], math.inf
    for e in _RV:
        d = (e[0][0] - r) ** 2 + (e[0][1] - g) ** 2 + (e[0][2] - b) ** 2
        if d < dist:
            best, dist = e, d
    if dist > 40 * 40 * 3:
        return None
    _, is_snow, dbz = best
    return ramp_color(SNOW, snow_rate(dbz)) if is_snow else ramp_color(RAIN, rain_rate(dbz))


@dataclass
class RadarFrame:
    t: int
    path: str
    template: str


def radar_frames(net: Net) -> list[RadarFrame]:
    ix = net.json(RAINVIEWER_INDEX)
    if not ix or not ix.get("host"):
        return []
    out = []
    for f in (ix.get("radar") or {}).get("past") or []:
        if isinstance(f.get("time"), int) and isinstance(f.get("path"), str):
            out.append(
                RadarFrame(
                    f["time"], f["path"], f"{ix['host']}{f['path']}/256/{{z}}/{{x}}/{{y}}/2/1_1.png"
                )
            )
    return sorted(out, key=lambda f: f.t)
