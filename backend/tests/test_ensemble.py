from __future__ import annotations

import random

from snowwatch.analysis import ensemble as ens
from snowwatch.analysis.series import Hourly

DAY = 24 * 3600


def system(n_members: int, n_days: int, seed: int) -> list[Hourly]:
    rng = random.Random(seed)
    return [
        {
            d * DAY + h * 3600: rng.choice([0.0, 0.0, 0.5, 2.0])
            for d in range(n_days)
            for h in range(24)
        }
        for _ in range(n_members)
    ]


def days(n: int) -> list[list[int]]:
    return [[d * DAY + h * 3600 for h in range(24)] for d in range(n)]


def test_running_totals_never_dip_and_pooled_stops_at_shortest() -> None:
    systems = {"gfs_seamless": system(31, 16, 1), "ecmwf_ifs025": system(51, 15, 2)}
    out = ens.running_totals(systems, days(16), min_members=10)
    for key in ("gfs_seamless", "ecmwf_ifs025"):
        p90 = [d.systems[key].p90 for d in out if d.systems[key] is not None]
        assert p90 == sorted(p90)
    assert all(d.tail is None and d.pooled is not None and d.pooled.n == 82 for d in out[:15])
    last = out[15]
    assert last.systems["ecmwf_ifs025"] is None
    assert last.tail == "gfs_seamless" and last.pooled is None
    assert last.systems["gfs_seamless"] is not None
    pooled_p90 = [d.pooled.p90 for d in out[:15] if d.pooled]
    assert pooled_p90 == sorted(pooled_p90)


def test_prototype_style_pooling_would_dip() -> None:
    """Why per-system totals matter: pooling whatever covers a day changes the member set."""
    gfs = [{h: 0.0 for d in days(16) for h in d} for _ in range(31)]
    ecmwf = [{h: 1.0 for d in days(15) for h in d} for _ in range(51)]
    naive_day14 = ens.stats(ens.member_totals(gfs + ecmwf, [h for d in days(15) for h in d]), 10)
    naive_day15 = ens.stats(ens.member_totals(gfs + ecmwf, [h for d in days(16) for h in d]), 10)
    assert naive_day14 and naive_day15 and naive_day15.p90 < naive_day14.p90  # the old dip
    out = ens.running_totals({"gfs_seamless": gfs, "ecmwf_ifs025": ecmwf}, days(16), min_members=10)
    assert out[15].tail == "gfs_seamless"


def test_too_few_members_gives_no_stats() -> None:
    assert ens.stats([1.0] * 9, 10) is None
    assert ens.exceedance([], 1.0) is None
    assert ens.exceedance([0.0, 1.0, 2.0, 3.0], 2.0) == 50
