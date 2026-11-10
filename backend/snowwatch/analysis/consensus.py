"""Period consensus.

While at least `min_models` deterministic models cover a period, the consensus
is their median; in the first periods the short-range models and the
high-resolution blend join that median. When too few models remain, the
ensemble mean takes over. The prototype's last-resort fallback (the median of
whatever is left plus the blend) is kept.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from snowwatch.analysis.series import Hourly, median, total


@dataclass
class PeriodConsensus:
    value: float | None
    basis: str | None  # "models" | "ensemble" | None
    nmodels: int
    models: dict[str, float | None] = field(default_factory=dict)
    blend: float | None = None


def blend_total(blend: Hourly | None, hours: Sequence[int]) -> float | None:
    """The prototype treats missing blend hours as zero."""
    if blend is None:
        return None
    return sum(blend.get(h) or 0.0 for h in hours)


def period_consensus(
    hours: Sequence[int],
    models: Mapping[str, Hourly],
    *,
    short_range: Mapping[str, Hourly] | None = None,
    blend: Hourly | None = None,
    early: bool = False,
    ens_mean: float | None = None,
    min_models: int = 3,
) -> PeriodConsensus:
    """Consensus for one period.

    models: the global deterministic models (always eligible).
    short_range / blend: join the median only when `early` (the first periods).
    ens_mean: used when fewer than min_models values remain.
    """
    sums = {m: total(s, hours) for m, s in models.items()}
    dets = [v for v in sums.values() if v is not None]
    bl = blend_total(blend, hours)
    if early:
        for m, s in (short_range or {}).items():
            v = total(s, hours)
            sums[m] = v
            if v is not None:
                dets.append(v)
        if bl is not None:
            dets.append(bl)
    if len(dets) >= min_models:
        return PeriodConsensus(median(dets), "models", len(dets), sums, bl)
    if ens_mean is not None:
        return PeriodConsensus(ens_mean, "ensemble", len(dets), sums, bl)
    rest = dets + ([bl] if bl is not None else [])
    if rest:
        return PeriodConsensus(median(rest), "models", len(dets), sums, bl)
    return PeriodConsensus(None, None, 0, sums, bl)
