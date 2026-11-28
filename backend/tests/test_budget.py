"""Milestone 4, richer ensembles: all three bands, a schedule per system, and the budget
planner that keeps public ensembles within the daily limit."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from snowwatch import budget, ensembles
from snowwatch.analysis.build import build_snapshot
from snowwatch.http import Fetcher
from snowwatch.inputs import inputs_from_responses, load_responses
from snowwatch.locations import service
from snowwatch.models import Location
from snowwatch.pipeline import run_all
from snowwatch.sources.openmeteo import ensemble_request
from snowwatch.store import repo
from tests.conftest import make_location
from tests.helpers import FIXTURES, SEED, captured_at, config, fixture_transport, seed

CFG = config()
ALL = list(CFG.ensembles)


def many(n: int) -> list[Location]:
    return [make_location(id=f"loc{i:02d}") for i in range(n)]


# --- the planner ----------------------------------------------------------------------


def test_tier_1_at_50_locations_fits_with_spots() -> None:
    plan = budget.plan(many(50), CFG, budget=10_000, public=ALL)
    assert plan.tier.n == 1 and plan.fits
    # 50 × 3 × ((3.54 + 5.83) × 4 + 2.4 × 2) ≈ 6,340, within 9,000 less 2,000 for spots.
    assert plan.weight == pytest.approx(6340, abs=15)
    assert plan.available == 7000


def test_adding_locations_drops_a_tier() -> None:
    tiers = {n: budget.plan(many(n), CFG, budget=10_000, public=ALL).tier.n for n in (50, 60)}
    assert tiers == {50: 1, 60: 2}
    plan = budget.plan(many(120), CFG, budget=10_000, public=ALL)
    assert plan.tier.n == 3 and plan.fits
    plan = budget.plan(many(400), CFG, budget=10_000, public=ALL)
    assert plan.tier.n == 4 and not plan.fits  # used anyway, and said so


def test_systems_served_locally_cost_nothing() -> None:
    plan = budget.plan(many(200), CFG, budget=10_000, public=[])
    assert plan.tier.n == 1 and plan.weight == 0
    gefs_only = budget.plan(many(50), CFG, budget=10_000, public=["gfs_seamless"])
    assert gefs_only.weight == pytest.approx(50 * 3 * 3.54 * 4, abs=5)


def test_without_a_server_the_forecasts_come_first_and_there_are_no_spots() -> None:
    plan = budget.plan(many(6), CFG, budget=10_000, public=ALL, local_forecasts=False)
    from snowwatch.sources.openmeteo import local_daily_weight

    fc = sum(local_daily_weight(loc, CFG) for loc in many(6))
    assert plan.available == pytest.approx(9000 - fc, abs=0.2) and plan.tier.n == 1


def test_tiers_and_their_runs() -> None:
    labels = [t.label for t in budget.TIERS]
    assert labels == [
        "3 bands, every run",
        "3 bands, 2 runs a day",
        "mid only, every run",
        "mid only, 2 runs a day",
    ]
    t1, t2 = budget.TIERS[0], budget.TIERS[1]
    assert len(budget.runs_for(CFG, "gfs_seamless", t1)) == 4
    assert len(budget.runs_for(CFG, "ecmwf_ifs025", t1)) == 4
    assert len(budget.runs_for(CFG, "gem_global", t1)) == 2  # GEPS runs 00z/12z only
    two = budget.runs_for(CFG, "gfs_seamless", t2)
    assert len(two) == 2 and two == sorted(two)
    a, b = (int(x[:2]) for x in two)
    assert b - a == 12  # 12 hours apart
    assert budget.runs_for(CFG, "gem_global", t2) == budget.runs_for(CFG, "gem_global", t1)


def test_a_system_is_asked_again_once_a_scheduled_time_passes() -> None:
    times = ["06:15", "18:15"]
    now = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
    assert budget.last_due(times, now) == datetime(2026, 12, 1, 6, 15, tzinfo=UTC)
    assert budget.last_due(times, now.replace(hour=3)) == datetime(2026, 11, 30, 18, 15, tzinfo=UTC)
    assert budget.ensemble_due(None, times, now)
    assert budget.ensemble_due(now - timedelta(hours=6), times, now)  # before 06:15
    assert not budget.ensemble_due(now - timedelta(hours=5), times, now)  # 07:00
    assert not budget.ensemble_due(now - timedelta(hours=5), [], now)


def test_the_old_single_schedule_still_reads() -> None:
    from snowwatch.config import Schedule

    s = Schedule(runs_utc=["00:30"], ensemble_runs_utc=["21:30", "09:30"])
    assert s.runs_for("gem_global") == ["09:30", "21:30"]


# --- requests and answers -------------------------------------------------------------


def test_three_band_answers_are_checked_at_every_point() -> None:
    req = ensemble_request(seed()["crystal"], "gem_global", bands=False)
    one = fixture_transport().handle_request(
        httpx.Request("GET", httpx.URL(req.url, params=req.params))
    )
    data = one.read()
    import json

    pt = json.loads(data)
    assert ensembles.members_with_data([pt, pt, pt]) == 21
    thin = {**pt, "hourly": {"time": pt["hourly"]["time"], "snowfall": pt["hourly"]["snowfall"]}}
    assert ensembles.members_with_data([pt, thin, pt]) == 1
    assert ensembles.reach_h([pt, pt, pt], captured_at()) == ensembles.reach_h(pt, captured_at())
    c = ensembles.compare([pt, pt, pt], pt, captured_at())
    assert c.max_diff_cm == 0 and c.members_local == c.members_public == 21


def three_bands(resp: Any, scale: tuple[float, float, float] = (0.5, 1.0, 1.6)) -> list[Any]:
    """A mid answer copied to three bands, each member's snowfall scaled per band."""
    out = []
    for f in scale:
        hourly = {
            k: [None if v is None else v * f for v in vals] if k != "time" else vals
            for k, vals in resp["hourly"].items()
        }
        out.append({**resp, "hourly": hourly})
    return out


def snapshot(responses: dict[str, Any]) -> Any:
    loc = seed()["crystal"]
    inputs = inputs_from_responses(loc, responses, CFG)
    return build_snapshot(loc, inputs, CFG, captured_at())[0], inputs


def test_each_band_uses_its_own_ensemble() -> None:
    base = load_responses(FIXTURES / "crystal")
    mid_only, _ = snapshot(base)
    banded = dict(base)
    for s in ALL:
        banded[f"ens_{s}"] = three_bands(base[f"ens_{s}"])
    own, inputs = snapshot(banded)
    assert set(inputs.ensemble_bands) == set(ALL) and set(inputs.ensembles) == set(ALL)
    # Mid is the same either way.
    assert own.bands[1].windows["d6_10"].ens == mid_only.bands[1].windows["d6_10"].ens
    # Base and summit: their own members, not mid's scaled ("estimated" no more).
    for i, f in ((0, 0.5), (2, 1.6)):
        w_own, w_mid = own.bands[i].windows["d6_10"], own.bands[1].windows["d6_10"]
        assert w_own.ens is not None and not w_own.ens.estimated
        assert w_own.members_cm and w_own.scale is None
        assert mid_only.bands[i].windows["d6_10"].ens is not None
        assert mid_only.bands[i].windows["d6_10"].ens.estimated
        e = [p.ens for p in own.bands[i].periods if p.ens is not None]
        assert e and not any(x.estimated for x in e)
        assert w_mid.ens is not None
        # The band's members are mid's × f in snow water (its own snow ratios apply).
        assert sum(w_own.members_cm_raw or []) == pytest.approx(
            f * sum(w_mid.members_cm_raw or []), rel=0.02
        )


def test_a_band_missing_any_system_scales_mids_instead() -> None:
    base = load_responses(FIXTURES / "crystal")
    mixed = dict(base)
    mixed["ens_gfs_seamless"] = three_bands(base["ens_gfs_seamless"])
    snap, _ = snapshot(mixed)
    w = snap.bands[0].windows["d6_10"]
    assert w.ens is not None and w.ens.estimated and w.scale is not None


# --- the run --------------------------------------------------------------------------


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    service.import_yaml(conn, SEED, max_locations=25)
    return conn


def ens_params(calls: list[httpx.Request]) -> list[str]:
    return [r.url.params["elevation"] for r in calls if "ensemble" in r.url.host]


def recording() -> tuple[list[httpx.Request], httpx.MockTransport]:
    inner = fixture_transport()
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return inner.handle_request(req)

    return calls, httpx.MockTransport(handler)


def test_a_run_asks_three_bands_and_follows_each_systems_schedule(
    seeded: sqlite3.Connection,
) -> None:
    calls, t = recording()
    f = Fetcher(user_agent="t", transport=t, sleep=lambda s: None)
    now = captured_at()  # 21:35 UTC
    run_all(seeded, f, CFG, now=now, spacing_s=0, only=["crystal"])
    elevs = ens_params(calls)
    assert len(elevs) == 3 and all(e.count(",") == 2 for e in elevs)
    snap = repo.latest_snapshot(seeded, "crystal")
    assert snap is not None and set(snap.ensembles) == set(ALL)
    assert snap.bands[0].windows["d6_10"].ens is not None
    assert not snap.bands[0].windows["d6_10"].ens.estimated
    # An hour later nothing is due; past GEFS's 00:15 only GEFS is asked again.
    calls.clear()
    run_all(seeded, f, CFG, now=now + timedelta(hours=1), spacing_s=0, only=["crystal"])
    assert ens_params(calls) == []
    calls.clear()
    with seeded:
        seeded.execute("UPDATE ensemble_cache SET fetched_at = ?", (now.isoformat(),))
    run_all(seeded, f, CFG, now=now + timedelta(hours=3), spacing_s=0, only=["crystal"])
    asked = [r.url.params["models"] for r in calls if "ensemble" in r.url.host]
    assert asked == ["gfs_seamless"]


def test_a_lower_tier_asks_mid_only(seeded: sqlite3.Connection, monkeypatch: Any) -> None:
    calls, t = recording()
    f = Fetcher(user_agent="t", transport=t, sleep=lambda s: None)
    real = budget.plan

    def tight(*a: Any, **kw: Any) -> budget.Plan:
        kw["budget"] = 2200  # after the forecasts, room only for mid-only ensembles
        return real(*a, **kw)

    monkeypatch.setattr(budget, "plan", tight)
    run_all(seeded, f, CFG, now=captured_at(), spacing_s=0, only=["crystal"])
    elevs = ens_params(calls)
    assert len(elevs) == 3 and all("," not in e for e in elevs)
    snap = repo.latest_snapshot(seeded, "crystal")
    assert snap is not None and snap.bands[0].windows["d6_10"].ens is not None
    assert snap.bands[0].windows["d6_10"].ens.estimated  # scaled from mid, as before


def test_spots_ask_the_server_at_three_bands(settings: Any, conn: sqlite3.Connection) -> None:
    from tests.test_spots import build

    log: list[str] = []
    snap = build(settings, conn, log=log, local_ensembles=True)
    assert snap.spot is not None and snap.spot.ensembles == "fresh"
    cells = [r[0] for r in conn.execute("SELECT DISTINCT cell FROM spot_ensembles")]
    assert len(cells) == 1 and cells[0].count("/") == 2  # three elevation steps
    # Public ensembles (no server downloads) stay at mid, within the allowance.
    log.clear()
    conn.execute("DELETE FROM spot_ensembles")
    build(settings, conn, log=log)
    cells = [r[0] for r in conn.execute("SELECT DISTINCT cell FROM spot_ensembles")]
    assert cells and all("/" not in c for c in cells)
