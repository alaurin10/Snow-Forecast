"""US forecast outside the HRDPS domain, for now: NOAA HRRR simulated radar by type from
Iowa State's IEM tile cache, repainted onto our ramps. Milestone 2 of docs/MAP-PLAN.md
replaces this with our own HRRR from NOAA's GRIB files.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from snowwatch.maps.geomet import Net, iso_ts
from snowwatch.maps.palette import MIX, RAIN, RGB, SNOW, hex_rgb

IEM = "https://mesonet.agron.iastate.edu"


def tile_template(minute: int) -> str:
    return f"{IEM}/cache/tile.py/1.0.0/hrrr::REFP-F{minute:04d}-0/{{z}}/{{x}}/{{y}}.png"


def hrrr_recolor(r: int, g: int, b: int) -> RGB | None:
    """IEM paints HRRR by type: greens/yellows rain, blues snow, purples/reds ice."""
    mx, mn = max(r, g, b) / 255, min(r, g, b) / 255
    light = (mx + mn) / 2
    d = mx - mn
    if d < 0.04:
        return None
    sat = d / (1 - abs(2 * light - 1)) if light not in (0, 1) else 0
    R, G, B = r / 255, g / 255, b / 255
    if mx == R:
        h = 60 * (((G - B) / d) % 6)
    elif mx == G:
        h = 60 * ((B - R) / d + 2)
    else:
        h = 60 * ((R - G) / d + 4)
    rain = [hex_rgb(c) for _, c in RAIN]
    snow = [hex_rgb(c) for _, c in SNOW]
    mix = [hex_rgb(c) for _, c in MIX]
    if 30 <= h < 65 and sat > 0.8:
        return rain[3] if h >= 48 else rain[4] if h >= 42 else rain[5]
    if 80 <= h < 170:
        return rain[0] if light > 0.75 else rain[1] if light > 0.45 else rain[2]
    if 170 <= h < 225:
        if light > 0.62:
            return snow[0]
        if light > 0.5:
            return snow[1]
        if light > 0.42:
            return snow[2]
        return snow[3] if light > 0.31 else snow[4]
    return mix[0] if light > 0.78 else mix[1]


def hrrr_slots(net: Net) -> dict[int, tuple[int, str]]:
    """Valid time → (IEM forecast minute, model run). Each slot comes from the newest run
    reaching it (hourly runs to 18 h, 6-hourly runs to 48 h), so read each slot's own JSON."""
    out: dict[int, tuple[int, str]] = {}

    def one(minute: int) -> tuple[int, int | None, str]:
        j = net.json(f"{IEM}/data/gis/images/4326/hrrr/refp_{minute:04d}.json")
        if not isinstance(j, dict) or not isinstance(j.get("model_forecast_utc"), str):
            return minute, None, ""
        return minute, iso_ts(j["model_forecast_utc"]), str(j.get("model_init_utc", ""))

    with ThreadPoolExecutor(4) as pool:
        for minute, valid, init in pool.map(one, range(0, 48 * 60 + 1, 60)):
            if valid is not None and valid not in out:
                out[valid] = (minute, init)
    return out
