"""A location's cloud layers, hour by hour: where the cloud is above it, for the map's 3D
clouds.

From one model's cloud cover at each pressure level (sources/openmeteo.py, CLOUD_LEVELS)
and the levels' heights: a layer is a run of levels with at least LAYER_MIN cover, its
base and top where the cover crosses LAYER_MIN between levels (straight-line between
them), its cover the most any of its levels has. Layers closer than MERGE_M are one.
At most MAX_LAYERS are kept, the lowest (the ones mountains reach).

It is an approximation: the levels are ~500 m apart through the heights mountains reach,
and a model's cloud at a pressure level is itself derived from the humidity there.
"""

from __future__ import annotations

from collections.abc import Iterable

from snowwatch.analysis.series import PointData
from snowwatch.doc import CloudsOut

LAYER_MIN = 15.0  # % cover at a level to count as cloud
MERGE_M = 300.0  # layers closer than this are one
MAX_LAYERS = 3
TOP_MARGIN_M = 300.0  # a layer reaching the highest level ends this far above it
HOUR = 3600


def _series(point: PointData, var: str) -> dict[int, float | None]:
    """A variable whether the response named it plainly (one model) or with the model."""
    if var in point.hourly:
        return point.hourly[var]
    for key, values in point.hourly.items():
        if key.startswith(var + "_"):
            return values
    return {}


def layers_at(levels: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    """Cloud layers from (height m, cover %) pairs: [(base m, top m, cover %)], lowest first."""
    prof = sorted((z, c) for z, c in levels)
    if len(prof) < 2:
        return []
    out: list[list[float]] = []
    i = 0
    n = len(prof)
    while i < n:
        if prof[i][1] < LAYER_MIN:
            i += 1
            continue
        j = i
        while j + 1 < n and prof[j + 1][1] >= LAYER_MIN:
            j += 1
        z0, c0 = prof[i]
        if i > 0:
            zb, cb = prof[i - 1]
            base = zb + (LAYER_MIN - cb) / (c0 - cb) * (z0 - zb) if c0 > cb else z0
        else:
            base = z0
        z1, c1 = prof[j]
        if j + 1 < n:
            za, ca = prof[j + 1]
            top = z1 + (c1 - LAYER_MIN) / (c1 - ca) * (za - z1) if c1 > ca else z1
        else:
            top = z1 + TOP_MARGIN_M
        cover = max(c for _, c in prof[i : j + 1])
        if out and base - out[-1][1] < MERGE_M:
            out[-1][1] = max(out[-1][1], top)
            out[-1][2] = max(out[-1][2], cover)
        else:
            out.append([base, top, cover])
        i = j + 1
    return [
        (max(0, round(b / 10) * 10), max(0, round(t / 10) * 10), round(min(100.0, c)))
        for b, t, c in out[:MAX_LAYERS]
    ]


def sky_cover(layers: Iterable[tuple[int, int, int]]) -> int:
    """The layers together as one cover (%), as if they were independent."""
    clear = 1.0
    for _, _, c in layers:
        clear *= 1 - c / 100
    return round(100 * (1 - clear))


def cloud_layers(
    point: PointData, model: str, levels: Iterable[int], *, start: int, hours: int
) -> CloudsOut | None:
    """Each hour's layers from `start` (an hour's start, Unix seconds) for `hours`; None
    if the response has no cloud cover at any level."""
    lv = list(levels)
    cover = {p: _series(point, f"cloud_cover_{p}hPa") for p in lv}
    height = {p: _series(point, f"geopotential_height_{p}hPa") for p in lv}
    if not any(v is not None for p in lv for v in cover[p].values()):
        return None
    start -= start % HOUR
    out_layers: list[list[tuple[int, int, int]]] = []
    out_cover: list[int | None] = []
    have = False
    for k in range(hours):
        t = start + k * HOUR
        prof = []
        for p in lv:
            z, c = height[p].get(t), cover[p].get(t)
            if z is not None and c is not None:
                prof.append((float(z), float(c)))
        if len(prof) < 2:
            out_layers.append([])
            out_cover.append(None)
            continue
        have = True
        lays = layers_at(prof)
        out_layers.append(lays)
        out_cover.append(sky_cover(lays))
    if not have:
        return None
    return CloudsOut(model=model, start=start, step_h=1, layers=out_layers, cover=out_cover)
