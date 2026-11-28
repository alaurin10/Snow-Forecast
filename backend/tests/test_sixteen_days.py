"""Milestone 4B, the data: forecasts to 16 days (today and the next 15), marked less
certain after 5 and 10 days, with no ski-day rating and no alerts past their limits."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path

import pytest

from snowwatch.analysis.build import LESS_CERTAIN_H, RATED_DAYS, build_snapshot
from snowwatch.api.models import OverviewRow
from snowwatch.api.public import _outlook
from snowwatch.doc import Snapshot
from snowwatch.inputs import inputs_from_responses, load_responses, load_stations
from snowwatch.sources import openmeteo as om
from tests.helpers import config, fixture_snapshot, seed

SERVER = Path(__file__).parent / "fixtures" / "live-20261128"  # 16-day blend, from the server


def captured(folder: Path) -> datetime:
    return datetime.fromisoformat(json.loads((folder / "meta.json").read_text())["captured_at"])


@cache
def server_snapshot(loc_id: str) -> Snapshot:
    inputs = inputs_from_responses(
        seed()[loc_id],
        load_responses(SERVER / loc_id),
        config(),
        stations=load_stations(SERVER / "shared"),
    )
    return build_snapshot(seed()[loc_id], inputs, config(), captured(SERVER))[0]


def days_ahead(snap: Snapshot, iso: str) -> float:
    return (datetime.fromisoformat(iso) - datetime.fromisoformat(snap.now)).total_seconds() / 86400


def test_the_blend_asks_for_16_days() -> None:
    req = om.blend_request(seed()["crystal"])
    assert req.params["forecast_days"] == "16" and req.params["past_days"] == "3"
    # 19 days with the past ones: past Open-Meteo's 14, so a public call weighs more.
    assert req.weight == pytest.approx(8.55)
    assert om.blend_request(seed()["crystal"], rich=True).params["forecast_days"] == "16"


@pytest.mark.parametrize("loc_id", ["crystal", "snoqualmie", "whistler"])
def test_a_server_forecast_reaches_day_16(loc_id: str) -> None:
    snap = server_snapshot(loc_id)
    first = date.fromisoformat(snap.now[:10])
    for band in snap.bands:
        assert len(band.periods) == 32
        assert days_ahead(snap, band.hourly.t[-1]) > 15.3
        assert date.fromisoformat(band.periods[-1].date) == first + timedelta(days=15)
        # The blend's own columns reach day 16 on the server (weather code, chance).
        assert band.hourly.wcode[-1] is not None and band.hourly.pop[-1] is not None
    assert len(snap.days) == 16 and snap.days[-1].date == (first + timedelta(days=15)).isoformat()
    assert set(snap.bands[1].hourly.snow_level_how) == {"wb"}  # humidity aloft to the end


def test_days_11_to_16_rest_on_the_ensembles() -> None:
    snap = server_snapshot("crystal")
    mid = snap.bands[1]
    late = [p for p in mid.periods if days_ahead(snap, p.start) > 10.5]
    assert late and all(p.basis == "ensemble" for p in late if p.swe_mm is not None)
    # Only GFS and ECMWF reach that far, and ECMWF stops ~14.7 days out.
    assert max(p.nmodels for p in late) <= 2 and min(p.nmodels for p in late) <= 1
    w = mid.windows["d11_16"]
    assert w.snow_cm is not None and w.ens is not None and not w.ens.estimated
    assert w.members_cm and w.ens.p10 <= w.ens.p50 <= w.ens.p90  # type: ignore[operator]


def test_less_certain_after_5_and_10_days() -> None:
    snap = server_snapshot("whistler")
    marks = [days_ahead(snap, t) for t in snap.less_certain_from]
    now_h = datetime.fromisoformat(snap.now).replace(minute=0, second=0, microsecond=0)
    assert LESS_CERTAIN_H == (120, 240)
    assert [round(m * 24) for m in marks] == [
        round(h - (datetime.fromisoformat(snap.now) - now_h).total_seconds() / 3600)
        for h in LESS_CERTAIN_H
    ]


@pytest.mark.parametrize("loc_id", ["crystal", "whistler"])
def test_no_ski_day_rating_past_day_10(loc_id: str) -> None:
    snap = server_snapshot(loc_id)
    first = date.fromisoformat(snap.now[:10])
    for d in snap.days:
        rated = (date.fromisoformat(d.date) - first).days < RATED_DAYS
        assert (d.rating is not None) == rated, d.date
        if not rated:
            assert d.reasons == [] and d.day_cm is not None  # the facts are still there


@pytest.mark.parametrize("loc_id", ["crystal", "snoqualmie", "whistler"])
def test_nothing_alerts_past_its_limit(loc_id: str) -> None:
    snap = server_snapshot(loc_id)
    first = date.fromisoformat(snap.now[:10])
    for f in snap.flags:
        if f.date:
            assert (date.fromisoformat(f.date) - first).days < 10, f
    assert snap.backcountry is not None and len(snap.backcountry.outlook) == 7


def test_a_short_blend_still_gives_16_days() -> None:
    """The older captures asked the blend for 11 days: the global models carry the hours
    on, so a lean public answer or an old cache doesn't cut the forecast at day 11."""
    snap = fixture_snapshot("crystal")
    mid = snap.bands[1]
    assert len(mid.periods) == 32 and days_ahead(snap, mid.hourly.t[-1]) > 15
    late = [i for i, t in enumerate(mid.hourly.t) if days_ahead(snap, t) > 11]
    assert all(mid.hourly.temp_c[i] is not None for i in late)
    assert all(mid.hourly.wcode[i] is None for i in late)  # the blend's own columns stop


def test_the_overview_gets_days_11_to_16() -> None:
    snap = server_snapshot("crystal")
    row = OverviewRow(id="crystal", name="Crystal", kind="resort", region="", country="US")
    _outlook(row, snap.bands[1])
    w = snap.bands[1].windows["d11_16"]
    assert row.d11_16_cm == w.snow_cm and w.ens is not None
    assert (row.d11_16_p10_cm, row.d11_16_p90_cm) == (w.ens.p10, w.ens.p90)
    # A snapshot from before milestone 4B has no such window: nothing is filled.
    old = snap.bands[1].model_copy(update={"windows": {"next5": w, "d6_10": w}})
    blank = OverviewRow(id="x", name="X", kind="resort", region="", country="US")
    _outlook(blank, old)
    assert blank.d11_16_cm is None


def test_reach_section_reports_each_models_last_hour() -> None:
    import httpx

    from snowwatch.checks import reach_section
    from snowwatch.http import Fetcher

    now = datetime(2026, 11, 28, 8, tzinfo=captured(SERVER).tzinfo)
    t0 = int(now.timestamp())
    hours = [t0 + 3600 * i for i in range(16 * 24)]

    def handler(req: httpx.Request) -> httpx.Response:
        if "models" not in req.url.params:
            vals: list[float | None] = [1.0] * len(hours)
            return httpx.Response(200, json={"hourly": {"time": hours, "temperature_2m": vals}})
        h: dict[str, list[object]] = {"time": list(hours)}
        for m, days in (("gfs_seamless", 15.5), ("icon_seamless", 7.0)):
            h[f"temperature_2m_{m}"] = [1.0 if i < days * 24 else None for i in range(len(hours))]
        return httpx.Response(200, json={"hourly": h})

    f = Fetcher(user_agent="t", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    lines = reach_section(f, seed()["crystal"], ["gfs_seamless", "icon_seamless", "x"], now)
    assert "| blend (`best_match`) | 16.0 |" in lines
    assert "| `gfs_seamless` | 15.5 |" in lines and "| `icon_seamless` | 7.0 |" in lines
    assert "| `x` | none |" in lines
