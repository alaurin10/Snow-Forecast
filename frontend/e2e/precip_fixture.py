"""Precipitation frames for the e2e server (e2e/serve.sh), so the map's timeline has
something to play: radar for the past two hours, a short nowcast and a day of hourly
forecast, at the real picture size over the real box, with bands of rain and snow that
drift east; snow totals for a few windows, more snow over a wider area the longer
the window; and clouds: a satellite picture, then forecast cloud cover with its heights
(a deck over the Cascades, based at 1,500 m with its top at 2,500 m); and the snow level
every 3 hours as rain, mix or snow, on a made-up ground (the real one needs the network).
Written fresh each run (no binaries in git).

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

from snowwatch.maps import bins, cloudheights, dataframe, totaldata
from snowwatch.maps.palette import (
    FINE_EXT,
    RAIN_T,
    SNOW_T,
    SNOWLINE,
    encode,
    encode_fine,
    fine_index,
    index_ramp,
    paint_total,
)
from snowwatch.maps.region import WEST, box_region, merc_x, merc_y
from snowwatch.maps.render import Renderer

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


def clouds(out: Path, region, now: int) -> list[dict]:
    """A satellite picture half an hour ago, then forecast clouds every 3 hours: a deck
    over the Cascades (1,500–2,500 m above sea level) drifting east and thinning; heights
    to 9 h with tops, to 15 h bases only, then the cover alone."""
    h, w = region.height, region.width
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    # Rainier and Crystal Mountain, in the box's pixels.
    cx = (merc_x(-121.6) - region.x0) / (region.x1 - region.x0) * w
    cy = (region.y1 - merc_y(46.9)) / (region.y1 - region.y0) * h
    r = Renderer(out, None)  # type: ignore[arg-type]
    frames: list[dict] = []
    sat = np.full((h, w, 3), 90, np.uint8)
    sat[ys.astype(int) % 200 < 100] = 200
    buf = io.BytesIO()
    Image.fromarray(sat, "RGB").save(buf, "WEBP", quality=40)
    name = f"c{now - 1800}-{hashlib.sha1(buf.getvalue()).hexdigest()[:12]}.webp"
    (out / name).write_bytes(buf.getvalue())
    frames.append(
        {
            "t": now - 1800,
            "file": name,
            "key": name,
            "kind": "observed",
            "span_h": 0,
            "hours": 0,
            "src": {"north": "goes"},
            "runs": {},
            "data": "",
        }
    )
    start = now // (3 * 3600) * (3 * 3600)
    ground = np.zeros((h, w), np.float32)
    for i in range(6):
        t = start + (i + 1) * 3 * 3600
        deck = np.exp(-((xs - cx - i * 25) ** 2 + (ys - cy) ** 2) / (2 * (160.0 - i * 10) ** 2))
        cover = np.clip(100 * deck * 1.4, 0, 100).astype(np.float32)
        heights = None
        if i < 3:
            lay = cloudheights.CloudLayer(
                np.full((h, w), 1500, np.float32),
                np.full((h, w), 2500, np.float32),
                cover,
            )
            none = cloudheights.CloudLayer(
                np.full((h, w), 7620, np.float32),
                np.full((h, w), 13716, np.float32),
                np.zeros((h, w), np.float32),
            )
            heights = cloudheights.from_layers([lay, none, none], cover * 0.3, ground)
        elif i < 5:
            heights = cloudheights.from_base(np.full((h, w), 1500, np.float32), cover, ground)
        picture = r._save_cloud(cover, f"k{t}")
        data = r._save_numbers(cloudheights.encode(cover, heights), f"kh{t}")
        frames.append(
            {
                "t": t,
                "file": picture,
                "key": picture,
                "kind": "forecast",
                "span_h": 0,
                "hours": 0,
                "src": {"north": "hrdps", "south": "nbm"},
                "runs": {"nbm": start},
                "data": data,
            }
        )
    return frames


def snow_level(out: Path, region, now: int) -> list[dict]:
    """The snow level every 3 hours for a day, rising from 1,200 m to 1,800 m, over a
    made-up ground of ridges up to 3,000 m: drawn as the server draws it (layers.py)."""
    h, w = region.height, region.width
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    ground = (1500 + 1500 * np.sin(xs / 60.0) * np.cos(ys / 80.0)).astype(np.float32)
    start = now // 10800 * 10800 + 10800
    frames = []
    for i in range(9):
        t = start + i * 10800
        level = np.full((h, w), 1200 + 75 * i, np.float32)
        above = ground - level
        png = encode(index_ramp(above, SNOWLINE))
        name = f"sl{t}-{hashlib.sha1(png).hexdigest()[:12]}.png"
        (out / name).write_bytes(png)
        data = totaldata.encode_level(above, level)
        numbers = f"sd{t}-{hashlib.sha1(data).hexdigest()[:12]}.{totaldata.EXT}"
        (out / numbers).write_bytes(data)
        frames.append(
            {
                "t": t,
                "file": name,
                "key": name,
                "kind": "forecast",
                "span_h": 0,
                "hours": 0,
                "src": {"north": "hrdps", "south": "nbm"},
                "runs": {},
                "data": numbers,
            }
        )
    return frames


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
        "layers": {
            "clouds": {"frames": clouds(out, region, now)},
            "snowlevel": {"frames": snow_level(out, region, now)},
        },
        "attribution": [],
    }
    (out / "index.json").write_text(json.dumps(index))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
