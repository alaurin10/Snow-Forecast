"""Precipitation frames for the e2e server (e2e/serve.sh), so the map's timeline has
something to play: radar for the past two hours, a short nowcast and a day of hourly
forecast, at the real picture size over the real box, with bands of rain and snow that
drift east; and snow totals for a few windows, more snow over a wider area the longer
the window. Written fresh each run (no binaries in git).

    uv run --frozen python ../frontend/e2e/precip_fixture.py <data>/precip
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from snowwatch.maps import bins, dataframe, totaldata
from snowwatch.maps.palette import FINE_EXT, RAIN_T, SNOW_T, encode_fine, fine_index, paint_total
from snowwatch.maps.region import WEST, box_region

WIDTH = 1700  # config/forecast.yaml map.width
RADAR = 10  # every 12 minutes
NOWCAST = 3
FORECAST = 24  # hourly


def picture(region, step: int, ds: int, blind: bool = False) -> tuple[bytes, bytes]:
    """Two bands of precipitation and a cell, moved a little east each step, drawn the way
    the server draws frames: a picture on the fine palette, and the numbers (dataframe.py)
    at 1/ds of the grid. `blind`: radar doesn't see round the cell, so the forecast filled
    it in (the map hatches it, or leaves it out)."""
    h, w = region.height, region.width
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = step * 9.0
    band1 = np.exp(-(((xs - 400 - dx) * 0.8 + (ys - 700) * 0.6) ** 2) / (2 * 90.0**2))
    band1 *= 0.5 + 0.5 * np.sin((ys + dx) / 70.0) ** 2
    band2 = np.exp(-(((xs - 900 - dx) * 0.7 - (ys - 1300) * 0.7) ** 2) / (2 * 60.0**2))
    cell = np.exp(-((xs - 1200 - dx) ** 2 + (ys - 500) ** 2) / (2 * 120.0**2))
    rate = (np.clip(band1 + 0.8 * band2 + cell, 0, 1) ** 2 * 6).astype(np.float32)  # mm/h
    kind = np.where(ys < 900, SNOW_T, RAIN_T).astype(np.uint8)  # north: snow, south: rain
    filled = None
    if blind:
        filled = np.zeros((h, w), np.float32)
        filled[300:700, 1000:1450] = 1.0
    return encode_fine(fine_index(rate, kind)), dataframe.encode(rate, kind, ds, filled)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    region = box_region(*WEST, WIDTH)
    now = int(time.time()) // 720 * 720
    frames = []
    times = (
        [("radar", now - (RADAR - 1 - i) * 720, 0) for i in range(RADAR)]
        + [("nowcast", now + (i + 1) * 720, 0) for i in range(NOWCAST)]
        + [("forecast", now // 3600 * 3600 + (i + 1) * 3600, 1) for i in range(FORECAST)]
    )
    for step, (kind, t, span) in enumerate(times):
        ds = 2 if kind == "forecast" else 1
        data, numbers = picture(region, step, ds, blind=kind != "forecast")
        prefix = {"radar": "r", "nowcast": "n", "forecast": "f"}[kind]
        name = f"{prefix}{t}-{hashlib.sha1(data).hexdigest()[:12]}.{FINE_EXT}"
        (out / name).write_bytes(data)
        data_name = f"{prefix}{t}-{hashlib.sha1(numbers).hexdigest()[:12]}.{dataframe.EXT}"
        (out / data_name).write_bytes(numbers)
        src = {"north": "hrdps", "south": "hrrr"} if kind == "forecast" else {}
        frames.append(
            {
                "t": t,
                "past": kind == "radar",
                "file": name,
                "key": name.split("-")[0],
                "south": "hrrr" if kind == "forecast" else "",
                "kind": kind,
                "span_h": span,
                "src": src,
                "palette": "fine",
                "data": data_name,
                "ds": ds,
                "valid": t - 1800 if kind == "forecast" else t,
            }
        )
    totals = []
    h, w = region.height, region.width
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    start = now // 3600 * 3600
    for window in (12, 24, 72, 240):
        reach = 150 + window * 3.0
        cm = (window / 2) * np.exp(-((xs - 700) ** 2 + (ys - 900) ** 2) / (2 * reach**2))
        buf = io.BytesIO()
        Image.fromarray(paint_total(cm.astype(np.float32)), "RGBA").save(buf, "PNG")
        png = buf.getvalue()
        name = f"t{window}-{hashlib.sha1(png).hexdigest()[:12]}.png"
        (out / name).write_bytes(png)
        totals.append(
            {
                "hours": window,
                "window": window,
                "start": start,
                "end": start + window * 3600,
                "file": name,
                "key": name,
                "source": "hrdps+nbm",
            }
        )
    # The snow total as numbers at each step of its slider: the same patch, and by
    # elevation nothing below 500 m, rising to 1.5 × the area total by 2,000 m and above.
    steps = []
    bh, bw = bins.shape_for(region)
    by, bx = np.mgrid[0:bh, 0:bw].astype(np.float32)
    rise = np.clip((bins.ELEVS - 500) / 1500, 0, 1) * 1.5
    for hours in totaldata.STEP_WINDOWS:
        reach = 150 + hours * 3.0
        cm = (hours / 2) * np.exp(-((xs - 700) ** 2 + (ys - 900) ** 2) / (2 * reach**2))
        cell = (hours / 2) * np.exp(-((bx * 2 - 700) ** 2 + (by * 2 - 900) ** 2) / (2 * reach**2))
        grid = cell[..., None] * rise[None, None, :]
        data = totaldata.encode(totaldata.area_plane(cm.astype(np.float32)), grid)
        name = f"s{hours}-{hashlib.sha1(data).hexdigest()[:12]}.{totaldata.EXT}"
        (out / name).write_bytes(data)
        steps.append({"end": start + hours * 3600, "hours": hours, "data": name})
    index = {
        "version": 3,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "region": region.key,
        "bounds": region.bounds,
        "width": region.width,
        "height": region.height,
        "now": frames[RADAR - 1]["t"],
        "frames": frames,
        "totals": totals,
        "steps": {"start": start, "key": "e2e", "steps": steps},
        "layers": {},
        "attribution": [],
    }
    (out / "index.json").write_text(json.dumps(index))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
