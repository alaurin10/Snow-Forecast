"""The full snapshot built from the captured responses of all six locations."""

from __future__ import annotations

import gzip

import pytest

from snowwatch.analysis.build import build_snapshot
from snowwatch.doc import Snapshot
from tests.helpers import captured_at, config, fixture_inputs, fixture_snapshot, seed

LOCS = ["crystal", "snoqualmie", "rainy", "whistler", "revelstoke", "sunshine"]


@pytest.mark.parametrize("loc_id", LOCS)
def test_hourly_adds_up_to_the_bars(loc_id: str) -> None:
    snap = fixture_snapshot(loc_id)
    for band in snap.bands:
        h = band.hourly
        for p in band.periods:
            if p.start not in h.t or p.swe_mm is None:
                continue
            i0 = h.t.index(p.start)
            idx = list(range(i0, i0 + p.hours))
            if idx[-1] >= len(h.t):
                continue  # period runs past the shown hours
            swe = sum(h.swe_mm[i] or 0 for i in idx)
            assert swe == pytest.approx(p.swe_mm, abs=0.05 + 0.005 * p.hours), (band.band, p.key)
            assert sum(h.snow_cm[i] or 0 for i in idx) == pytest.approx(p.snow_cm or 0, abs=0.1)


@pytest.mark.parametrize("loc_id", LOCS)
def test_document_shape_and_size(loc_id: str) -> None:
    snap = fixture_snapshot(loc_id)
    assert [b.band for b in snap.bands] == ["base", "mid", "summit"]
    for band in snap.bands:
        assert len(band.periods) == 20 and len(band.hourly.t) == 240
        assert band.windows["next5"].snow_cm is not None
    assert snap.bands[1].windows["next5"].members_cm  # mid carries the member totals
    others = [b.windows["next5"].ens for b in (snap.bands[0], snap.bands[2])]
    assert all(e is None or e.estimated for e in others)
    assert set(snap.ensembles) == {"gfs_seamless", "ecmwf_ifs025", "gem_global"}
    assert snap.warnings == []
    blob = gzip.compress(snap.model_dump_json().encode())
    assert len(blob) < 60 * 1024
    assert Snapshot.model_validate_json(snap.model_dump_json()) == snap


@pytest.mark.parametrize("loc_id", LOCS)
def test_backcountry_ridge_and_days(loc_id: str) -> None:
    snap = fixture_snapshot(loc_id)
    assert snap.ridge is not None and len(snap.ridge.kmh) == 240
    assert snap.ridge.level_m == snap.bands[2].elev_m
    bc = snap.backcountry
    assert bc is not None
    assert [r.window for r in bc.rose] == ["past72", "next48", "past48", "next24", "next72"]
    for rose in bc.rose:
        assert len(rose.sectors) == 8
        assert sum(rose.sectors) == pytest.approx(1, abs=0.01) or sum(rose.sectors) == 0
    assert len(bc.refreeze) == 9 and {n.band for n in bc.refreeze} == {"base", "mid", "summit"}
    assert len(bc.sky) == 3 and bc.storm.next48_cm is not None
    days = [p for p in snap.bands[1].periods if p.kind == "day"]
    assert [d.date for d in snap.days] == [p.date for p in days]
    resort = snap.location.kind == "resort"
    assert all((d.rating is not None) == resort for d in snap.days)
    assert all(len(d.reasons) <= 3 for d in snap.days)
    # The day's snow is the mid-band day bar.
    assert [d.day_cm for d in snap.days] == [p.snow_cm for p in days]


@pytest.mark.parametrize("loc_id", LOCS)
def test_running_band_never_dips(loc_id: str) -> None:
    daily = fixture_snapshot(loc_id).daily
    assert 15 <= len(daily) <= 16
    p90 = [d.pooled_cum.p90 for d in daily if d.pooled_cum and d.pooled_cum.p90 is not None]
    assert p90 == sorted(p90)
    for system in ("gfs_seamless", "ecmwf_ifs025", "gem_global"):
        vals = [d.ens_cum[system].p90 for d in daily if d.ens_cum.get(system)]
        assert vals == sorted(vals)
    # ECMWF ENS ends first. The pooled band stops there (no splice) and the
    # GEFS band, present every day, carries on.
    tails = [d for d in daily if d.pooled_tail]
    assert all(d.pooled_cum is None and d.pooled_tail == "gfs_seamless" for d in tails)
    assert all(d.ens_cum["gfs_seamless"] for d in daily)


def test_slr_depth_is_at_least_raw_when_cold() -> None:
    w = fixture_snapshot("whistler").bands[2].windows["next5"]
    assert w.snow_cm_slr is not None and w.snow_cm_raw is not None
    assert w.snow_cm_slr > w.snow_cm_raw


def test_us_locations_use_short_range_models() -> None:
    p0 = fixture_snapshot("crystal").bands[1].periods[0]
    assert "ncep_hrrr_conus" in p0.models and p0.basis == "models"


def test_missing_ensembles_and_upper_air_are_tolerated() -> None:
    inputs = fixture_inputs("rainy")
    bare = type(inputs)(blend=inputs.blend, multi=inputs.multi)
    snap, _ = build_snapshot(seed()["rainy"], bare, config(), captured_at())
    mid = snap.bands[1]
    assert mid.windows["next5"].ens is None and mid.periods[0].ens is None
    assert all(p.basis in ("models", None) for p in mid.periods)
    assert snap.ensembles == {}
    # Without free-air data the rose falls back to the summit's own wind.
    assert snap.ridge is None and snap.backcountry is not None
    assert snap.backcountry.rose[1].mean_kmh is not None


def test_tz_mismatch_is_reported() -> None:
    inputs = fixture_inputs("crystal")
    odd = type(inputs)(blend=inputs.blend, multi=inputs.multi)
    loc = seed()["crystal"].model_copy(update={"tz": "America/Denver"})
    snap, _ = build_snapshot(loc, odd, config(), captured_at())
    assert any("timezone" in w for w in snap.warnings)


def test_forecast_daily_records() -> None:
    _, recs = build_snapshot(seed()["crystal"], fixture_inputs("crystal"), config(), captured_at())
    sources = {r.source for r in recs}
    assert {"cons", "gfs_seamless", "ecmwf_ifs025", "ens_p50"} <= sources
    # Days start today in the location's timezone (captured 4 Nov, early afternoon).
    assert min(r.target_date for r in recs) == "2026-11-04"
    assert all(r.snow_cm is None or r.snow_cm >= 0 for r in recs)


def test_flags_are_in_the_snapshot() -> None:
    whistler = fixture_snapshot("whistler")
    assert any(f.type == "powder_day" for f in whistler.flags)
    order = {"warning": 0, "notice": 1, "info": 2}
    for loc_id in LOCS:
        flags = fixture_snapshot(loc_id).flags
        assert [order[f.severity] for f in flags] == sorted(order[f.severity] for f in flags)


def test_consensus_records_cover_calendar_days() -> None:
    """The scorecard compares calendar days, so the consensus record for a date is
    the hourly consensus from local midnight to midnight, like the models' records."""
    from collections import defaultdict
    from datetime import datetime

    loc = seed()["crystal"]
    snap, records = build_snapshot(loc, fixture_inputs("crystal"), config(), captured_at())
    mid = snap.bands[1].hourly
    by_day: dict[str, float] = defaultdict(float)
    for t, swe in zip(mid.t, mid.swe_mm, strict=True):
        by_day[datetime.fromisoformat(t).date().isoformat()] += swe or 0.0
    cons = {r.target_date: r for r in records if r.source == "cons"}
    full_days = sorted(cons)[1:4]  # skip today, which starts part-way through
    assert full_days
    k = config().snowfall_cm_per_mm
    for d in full_days:
        assert cons[d].snow_cm == pytest.approx(by_day[d] * k, abs=0.15)


def _slr_snapshot(loc_id: str) -> Snapshot:
    assert config().depth_method == "slr"  # the shipped setting
    return fixture_snapshot(loc_id)


@pytest.mark.parametrize("loc_id", LOCS)
def test_every_total_is_the_sum_of_headline_periods(loc_id: str) -> None:
    """With depth_method: slr, every depth the snapshot surfaces is in the
    temperature-based depth, and every total is the sum of its periods' bars."""
    snap = _slr_snapshot(loc_id)
    assert snap.depth_method == "slr"
    for band in snap.bands:
        ps = band.periods
        for p in ps:
            assert p.snow_cm == p.snow_cm_slr, (band.band, p.key)
            if p.swe_mm and p.snow_cm and p.swe_mm >= 2:
                # The bar is the period's snow water at its own ratio.
                f = p.snow_cm / p.swe_mm
                expected = (p.slr / 10) if p.slr else config().snowfall_cm_per_mm
                assert f == pytest.approx(expected, rel=0.06, abs=0.05), (band.band, p.key)
        for name, (a, b) in (("next5", (0, 10)), ("d6_10", (10, 20))):
            w = band.windows[name]
            total = sum(p.snow_cm or 0 for p in ps[a:b])
            assert w.snow_cm == pytest.approx(total, abs=0.05 * (b - a)), (band.band, name)
            assert w.snow_cm == w.snow_cm_slr
            assert w.ens == w.ens_slr
        assert band.stats.next5_cm == band.windows["next5"].snow_cm
        assert band.stats.d6_10_cm == band.windows["d6_10"].snow_cm
    mid = snap.bands[1].windows["next5"]
    if mid.ens is not None:
        assert mid.members_cm == sorted(mid.members_cm)
        assert mid.ens.p50 is not None
        assert min(mid.members_cm) <= mid.ens.p50 <= max(mid.members_cm)
    # Days (ski-day ratings, powder flags) are built from the same bars.
    days = [p for p in snap.bands[1].periods if p.kind == "day"]
    assert [d.day_cm for d in snap.days] == [p.snow_cm for p in days]
    # The Backcountry storm total is the summit's hourly headline depth.
    bc = snap.backcountry
    assert bc is not None and bc.storm.next48_cm is not None
    top = snap.bands[2].hourly
    assert bc.storm.next48_cm == pytest.approx(sum(v or 0 for v in top.snow_cm[:48]), abs=0.3)


@pytest.mark.parametrize("loc_id", ["whistler", "crystal"])
def test_depth_method_switches_every_depth(loc_id: str) -> None:
    """The same inputs built under raw and slr: snow water is identical, and every
    depth follows the method (cold snow piles up deeper than 7:1)."""
    loc, inputs = seed()[loc_id], fixture_inputs(loc_id)
    raw_cfg = config().model_copy(update={"depth_method": "raw"})
    raw, raw_recs = build_snapshot(loc, inputs, raw_cfg, captured_at())
    slr, slr_recs = build_snapshot(loc, inputs, config(), captured_at())
    assert raw.depth_method == "raw"
    for rb, sb in zip(raw.bands, slr.bands, strict=True):
        assert [p.swe_mm for p in rb.periods] == [p.swe_mm for p in sb.periods]
        assert [p.snow_cm for p in rb.periods] == [p.snow_cm_raw for p in sb.periods]
        assert rb.windows["next5"].snow_cm == sb.windows["next5"].snow_cm_raw
        assert rb.windows["next5"].ens == sb.windows["next5"].ens_raw
        assert rb.windows["next5"].ens == rb.windows["next5"].ens_raw
    # The records are the same either way: the scorecard and trend pick a source.
    assert raw_recs == slr_recs
    if loc_id == "whistler":  # a cold storm
        w_raw, w_slr = raw.bands[2].windows["next5"], slr.bands[2].windows["next5"]
        assert w_slr.snow_cm is not None and w_raw.snow_cm is not None
        assert w_slr.snow_cm > w_raw.snow_cm
        assert slr.bands[1].stats.next24_cm is not None
        # Model agreement and the ensemble range grow with it.
        assert slr.daily[4].pooled_cum is not None and raw.daily[4].pooled_cum is not None
        assert (slr.daily[4].pooled_cum.p90 or 0) > (raw.daily[4].pooled_cum.p90 or 0)
        cum = [(slr.daily[4].models_cum.get(m), raw.daily[4].models_cum.get(m)) for m in raw.models]
        assert any(a > b for a, b in cum if a is not None and b is not None)
