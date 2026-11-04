"""Hourly series that agree with the period bars.

Precipitation: the hourly *shape* comes from the short-range models for the
first 48 h and from the deterministic model median after that; each period is
then scaled so its hours add up to the period consensus. Continuous variables
(temperature, freezing level, wind, cloud) are the hourly median across models,
with the model range as a band.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from snowwatch.analysis.series import Hourly, median

PRECIP_MM = 0.1  # a model "shows precipitation" in an hour at or above this


def shape_value(
    h: int,
    models: Mapping[str, Hourly],
    short_range: Mapping[str, Hourly],
    short_until: int,
    fallback: Hourly | None = None,
) -> float | None:
    if h < short_until:
        v = median(s.get(h) for s in short_range.values())
        if v is not None:
            return v
    v = median(s.get(h) for s in models.values())
    if v is None and fallback is not None:
        v = fallback.get(h)
    return v


def scale_to_total(
    hours: Sequence[int],
    shape: Mapping[int, float | None],
    target: float | None,
    support: Mapping[int, float] | None = None,
) -> dict[int, float | None]:
    """Rescale shape over hours so it sums to target.

    If the shape is all zero but the target isn't, spread the target over the
    hours with support (how many models show precipitation), or evenly.
    """
    if target is None:
        return {h: None for h in hours}
    if target <= 0:
        return {h: 0.0 for h in hours}
    base = {h: max(0.0, shape.get(h) or 0.0) for h in hours}
    s = sum(base.values())
    if s <= 0 and support:
        base = {h: max(0.0, support.get(h, 0.0)) for h in hours}
        s = sum(base.values())
    if s <= 0:
        base = {h: 1.0 for h in hours}
        s = float(len(hours))
    return {h: base[h] * target / s for h in hours}


def support_counts(hours: Sequence[int], series: Sequence[Hourly]) -> dict[int, float]:
    """How many models show precipitation in each hour."""
    return {h: float(sum(1 for s in series if (s.get(h) or 0) >= PRECIP_MM)) for h in hours}


def consensus_line(
    hours: Sequence[int],
    models: Mapping[str, Hourly],
    short_range: Mapping[str, Hourly],
    short_until: int,
    fallback: Hourly | None = None,
) -> tuple[dict[int, float | None], dict[int, float | None], dict[int, float | None]]:
    """Median line (following the short-range models early) and the min–max band."""
    mid: dict[int, float | None] = {}
    lo: dict[int, float | None] = {}
    hi: dict[int, float | None] = {}
    every = {**models, **short_range}
    for h in hours:
        vals = [v for s in every.values() if (v := s.get(h)) is not None]
        mid[h] = shape_value(h, models, short_range, short_until, fallback)
        lo[h] = min(vals) if vals else None
        hi[h] = max(vals) if vals else None
    return mid, lo, hi
