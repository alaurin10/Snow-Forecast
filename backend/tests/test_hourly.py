from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from snowwatch.analysis.hourly import consensus_line, scale_to_total, shape_value
from snowwatch.analysis.periods import build_periods
from snowwatch.settings import REPO_ROOT

H = [0, 3600, 7200, 10800]


def test_scaling_preserves_shape_and_total() -> None:
    out = scale_to_total(H, {0: 1.0, 3600: 3.0, 7200: 0.0, 10800: None}, 8.0)
    assert out == {0: 2.0, 3600: 6.0, 7200: 0.0, 10800: 0.0}


def test_zero_shape_uses_support_then_even() -> None:
    zero = dict.fromkeys(H, 0.0)
    assert scale_to_total(H, zero, 4.0, {0: 0, 3600: 3, 7200: 1, 10800: 0}) == {
        0: 0.0,
        3600: 3.0,
        7200: 1.0,
        10800: 0.0,
    }
    assert scale_to_total(H, zero, 4.0) == dict.fromkeys(H, 1.0)


def test_no_target_and_zero_target() -> None:
    assert scale_to_total(H, {}, None) == dict.fromkeys(H)
    assert scale_to_total(H, {0: 5.0}, 0.0) == dict.fromkeys(H, 0.0)


def test_short_range_models_lead_early() -> None:
    models = {"gfs": {0: 1.0, 7200: 1.0}, "ecmwf": {0: 3.0, 7200: 3.0}}
    short = {"hrrr": {0: 10.0, 7200: 10.0}}
    assert shape_value(0, models, short, short_until=3600) == 10.0
    assert shape_value(7200, models, short, short_until=3600) == 2.0
    mid, lo, hi = consensus_line([0], models, short, 3600)
    assert (mid[0], lo[0], hi[0]) == (10.0, 1.0, 10.0)


def test_crystal_17_oct_regression() -> None:
    """The prototype's hourly chart showed 14.7 in for days 6–10 while the bars said 0.9 in.

    Scaling the same hourly blend to the period consensus must give the bars' total.
    """
    raw = (
        subprocess.run(
            ["git", "show", "HEAD:docs/reference/sample/raw/crystal.json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        or (REPO_ROOT / "docs/reference/sample/raw/crystal.json").read_text()
    )
    doc = json.loads(raw)
    tz = ZoneInfo("America/Los_Angeles")
    snow = {
        int(datetime.fromisoformat(h["t"]).replace(tzinfo=tz).timestamp()): h["snow"]
        for h in doc["hourly"]
    }
    periods = build_periods(sorted(snow), tz, date(2026, 10, 17))
    cons = {p["key"]: p["cons"] for p in doc["periods"]}
    later = [p for p in periods if p.key in cons][10:20]
    before = sum(snow[h] or 0 for p in later for h in p.hours)
    after = sum(
        v or 0
        for p in later
        for v in scale_to_total(p.hours, {h: snow[h] for h in p.hours}, cons[p.key]).values()
    )
    assert before == pytest.approx(14.7, abs=0.2)
    assert after == pytest.approx(sum(cons[p.key] for p in later), abs=0.01)
    assert after == pytest.approx(0.9, abs=0.05)
