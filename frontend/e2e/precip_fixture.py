"""Precipitation frames for the e2e server (e2e/serve.sh), so the map's timeline has
something to play: radar for the past two hours, a short nowcast and a day of hourly
forecast, at the real picture size over the real box, with bands of rain and snow that
drift east. Written fresh each run (no binaries in git).

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

from snowwatch.maps.region import WEST, box_region

WIDTH = 1700  # config/forecast.yaml map.width
RADAR = 10  # every 12 minutes
NOWCAST = 3
FORECAST = 24  # hourly


def picture(region, step: int) -> bytes:
    """Two bands of precipitation and a cell, moved a little east each step."""
    h, w = region.height, region.width
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = step * 9.0
    band1 = np.exp(-(((xs - 400 - dx) * 0.8 + (ys - 700) * 0.6) ** 2) / (2 * 90.0**2))
    band1 *= 0.5 + 0.5 * np.sin((ys + dx) / 70.0) ** 2
    band2 = np.exp(-(((xs - 900 - dx) * 0.7 - (ys - 1300) * 0.7) ** 2) / (2 * 60.0**2))
    cell = np.exp(-((xs - 1200 - dx) ** 2 + (ys - 500) ** 2) / (2 * 120.0**2))
    v = np.clip(band1 + 0.8 * band2 + cell, 0, 1)
    rgba = np.zeros((h, w, 4), np.uint8)
    on = v > 0.12
    snow = ys < 900  # north: snow, south: rain
    rgba[..., 0] = np.where(snow, 200, 40)
    rgba[..., 1] = np.where(snow, 220, 140)
    rgba[..., 2] = 255
    rgba[..., 3] = np.where(on, (80 + 175 * v).astype(np.uint8), 0)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", compress_level=1)
    return buf.getvalue()


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
        data = picture(region, step)
        prefix = {"radar": "r", "nowcast": "n", "forecast": "f"}[kind]
        name = f"{prefix}{t}-{hashlib.sha1(data).hexdigest()[:12]}.png"
        (out / name).write_bytes(data)
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
            }
        )
    index = {
        "version": 2,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "region": region.key,
        "bounds": region.bounds,
        "width": region.width,
        "height": region.height,
        "now": frames[RADAR - 1]["t"],
        "frames": frames,
        "totals": [],
        "layers": {},
        "attribution": [],
    }
    (out / "index.json").write_text(json.dumps(index))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
