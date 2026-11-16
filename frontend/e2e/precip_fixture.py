"""Precipitation frames for the e2e server (e2e/serve.sh), so the map's timeline has
something to play: radar for the past two hours, a short nowcast and a day of hourly
forecast, at the real picture size over the real box, with bands of rain and snow that
drift east. Written fresh each run (no binaries in git).

    uv run --frozen python ../frontend/e2e/precip_fixture.py <data>/precip
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

from snowwatch.maps.palette import FINE_EXT, RAIN_T, SNOW_T, encode_fine, fine_index, fine_spec
from snowwatch.maps.region import WEST, box_region

WIDTH = 1700  # config/forecast.yaml map.width
RADAR = 10  # every 12 minutes
NOWCAST = 3
FORECAST = 24  # hourly


def picture(region, step: int) -> bytes:
    """Two bands of precipitation and a cell, moved a little east each step, drawn the way
    the server draws frames (palette.fine_index on the fine palette)."""
    h, w = region.height, region.width
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = step * 9.0
    band1 = np.exp(-(((xs - 400 - dx) * 0.8 + (ys - 700) * 0.6) ** 2) / (2 * 90.0**2))
    band1 *= 0.5 + 0.5 * np.sin((ys + dx) / 70.0) ** 2
    band2 = np.exp(-(((xs - 900 - dx) * 0.7 - (ys - 1300) * 0.7) ** 2) / (2 * 60.0**2))
    cell = np.exp(-((xs - 1200 - dx) ** 2 + (ys - 500) ** 2) / (2 * 120.0**2))
    rate = (np.clip(band1 + 0.8 * band2 + cell, 0, 1) ** 2 * 6).astype(np.float32)  # mm/h
    kind = np.where(ys < 900, SNOW_T, RAIN_T).astype(np.uint8)  # north: snow, south: rain
    return encode_fine(fine_index(rate, kind))


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
        name = f"{prefix}{t}-{hashlib.sha1(data).hexdigest()[:12]}.{FINE_EXT}"
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
                "palette": "fine",
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
        "fine": fine_spec(),
    }
    (out / "index.json").write_text(json.dumps(index))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
