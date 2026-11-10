"""Where HRRR has nothing: NWS WPC 6-hour precipitation totals, drawn in tan (no type).
To be removed in milestone 2 of docs/MAP-PLAN.md, when our own HRRR and NBM replace it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from snowwatch.maps.geomet import Net, iso_ts
from snowwatch.maps.palette import UNTYPED, ramp_color
from snowwatch.maps.region import Region, merc_x, merc_y

HOUR = 3600
WPC = "https://mapservices.weather.noaa.gov/vector/rest/services/precip/wpc_qpf/MapServer"


@dataclass
class Wpc:
    base: int
    issued: str


def wpc_info(net: Net) -> Wpc | None:
    j = net.json(
        f"{WPC}/13/query",
        {
            "where": "1=1",
            "outFields": "start_time,issue_time",
            "returnGeometry": "false",
            "resultRecordCount": "1",
            "f": "json",
        },
    )
    try:
        a = j["features"][0]["attributes"]
        return Wpc(wpc_ts(a["start_time"]), str(a.get("issue_time", "")))
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def wpc_ts(s: str) -> int:
    """'2026-11-07 12:00:00' (UTC) → Unix seconds."""
    return iso_ts(s.replace(" ", "T") + "Z")


def wpc_layer(t: int, base: int) -> int | None:
    """Layer 13 holds hours 0–6 from `base`, 14 holds 6–12, … 25 holds 72–78."""
    i = (t - HOUR - base) // (6 * HOUR)
    return 13 + i if 0 <= i <= 12 else None


def wpc_draw(net: Net, layer: int, region: Region) -> np.ndarray | None:
    fc = net.json(
        f"{WPC}/{layer}/query",
        {
            "where": "qpf>=0.1",
            "outFields": "qpf",
            "returnGeometry": "true",
            "maxAllowableOffset": "0.02",
            "geometryPrecision": "3",
            "outSR": "4326",
            "f": "geojson",
        },
    )
    if not isinstance(fc, dict) or not isinstance(fc.get("features"), list):
        return None
    sx = region.width / (region.x1 - region.x0)
    sy = region.height / (region.y1 - region.y0)

    def pix(lon: float, lat: float) -> tuple[float, float]:
        return (merc_x(lon) - region.x0) * sx, (region.y1 - merc_y(lat)) * sy

    out = Image.new("RGBA", (region.width, region.height), (0, 0, 0, 0))
    feats = sorted(fc["features"], key=lambda f: (f.get("properties") or {}).get("qpf", 0))
    for f in feats:
        color = ramp_color(UNTYPED, float((f.get("properties") or {}).get("qpf", 0)))
        geom = f.get("geometry") or {}
        if not color or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        mask = Image.new("L", out.size, 0)
        draw = ImageDraw.Draw(mask)
        for poly in polys:
            for i, ring in enumerate(poly):
                if len(ring) >= 3:
                    draw.polygon([pix(x, y) for x, y in ring], fill=0 if i else 1)
        out.paste((*color, 255), (0, 0), mask.point(lambda v: 255 if v else 0))
    return np.asarray(out)
