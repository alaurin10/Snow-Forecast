"""Clouds: NOAA GOES-West's GeoColor imagery (CIRA's true colour by day, infrared with
city lights by night), every 10 minutes, from NASA GIBS as Web Mercator tiles.

  gibs.earthdata.nasa.gov/wmts/epsg3857/best/GOES-West_ABI_GeoColor/default/<time>/
      GoogleMapsCompatible_Level7/{z}/{row}/{col}.png

The times that exist come from GIBS's time-domain request for the layer (a few hundred
bytes, unlike the 6 MB capabilities document). Some 10-minute steps are missing. Free,
no key.
"""

from __future__ import annotations

import re

from snowwatch.maps.geomet import Net, parse_times, ts_iso

BASE = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
LAYER = "GOES-West_ABI_GeoColor"
MATRIX = "GoogleMapsCompatible_Level7"
ZOOM = 6  # 1.5–2 km a pixel over the West box, about the frames' own resolution
STEP_S = 30 * 60  # one frame each half hour
SLACK_S = 10 * 60  # a missing half-hour image takes the one before, up to this old
HISTORY_S = 3 * 3600


def times(net: Net, start: int, end: int) -> list[int]:
    """Image times GIBS has between two moments."""
    url = f"{BASE}/1.0.0/{LAYER}/default/{MATRIX}/all/{ts_iso(start)}--{ts_iso(end)}.xml"
    r = net.get(url)
    if r is None:
        return []
    m = re.search(r"<Domain>([^<]*)</Domain>", r.text)
    return [t for t in parse_times(m.group(1)) if start <= t <= end] if m else []


def pick(available: list[int], now: int, history_s: int = HISTORY_S) -> list[int]:
    """One image per half hour over the last three hours: the image on the half hour, or
    the newest up to 10 minutes before it."""
    have = sorted(set(available))
    out: list[int] = []
    top = now - now % STEP_S
    for slot in range(top - history_s, top + 1, STEP_S):
        best = [t for t in have if slot - SLACK_S <= t <= slot]
        if best and best[-1] not in out:
            out.append(best[-1])
    return out


def template(t: int) -> str:
    """Tile URL for an image time, with `{z}`, `{x}`, `{y}` for `region.stitch`."""
    return f"{BASE}/{LAYER}/default/{ts_iso(t)}/{MATRIX}/{{z}}/{{y}}/{{x}}.png"
