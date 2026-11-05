"""BC River Forecast Centre snow pillows: parsing, daily readings, station lookup."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from snowwatch.http import Fetcher
from snowwatch.locations.resolve import ResolveIn, resolve
from snowwatch.models import Location
from snowwatch.pipeline import fetch_bc
from snowwatch.sources import bc_asws
from snowwatch.store import repo
from tests.helpers import BC_DATA, seed

BC = Path(__file__).parent / "fixtures" / "bc"


def test_wide_csv_keeps_only_the_wanted_stations() -> None:
    data = bc_asws.parse_wide_csv((BC / "SD.csv").read_text(), {"3A20P"})
    assert list(data) == ["3A20P"]
    t, v = data["3A20P"][0]
    assert t.endswith("+00:00") and isinstance(v, float)
    everything = bc_asws.parse_wide_csv((BC / "SD.csv").read_text())
    assert {"1A01P", "2C14P", "3A20P"} <= set(everything)


def test_blank_cells_and_bad_rows_are_skipped() -> None:
    text = (
        "DATE(UTC),3A20P Callaghan Creek\n2026-11-01 00:00,12.0\n2026-11-01 01:00,\nnot a date,5\n"
    )
    assert bc_asws.parse_wide_csv(text) == {"3A20P": [("2026-11-01T00:00+00:00", 12.0)]}


def test_station_rows_from_the_wfs() -> None:
    rows = bc_asws.station_rows(json.loads((BC / "stations.json").read_text()))
    by_id = {r["triplet"]: r for r in rows}
    assert by_id["3A20P:BC:ASWS"]["name"] == "Callaghan Creek"
    assert by_id["3A20P:BC:ASWS"]["elev_m"] == 1017
    assert "2A17P:BC:ASWS" not in by_id  # inactive


def bc_data() -> dict[str, dict[str, list[tuple[str, float]]]]:
    keep = {"3A20P", "2A06P", "2C14P"}
    return {
        el: bc_asws.parse_wide_csv((BC / f"{el}.csv").read_text(), keep) for el in bc_asws.ELEMENTS
    }


def test_daily_start_of_day_readings_and_changes() -> None:
    data = bc_asws.station_slice(bc_data(), "3A20P", datetime(2026, 10, 1, tzinfo=UTC))
    snow = bc_asws.parse_station(
        "3A20P:BC:ASWS",
        data,
        {"name": "Callaghan Creek", "elevation": 1017 / 0.3048},
        "America/Vancouver",
    )
    assert snow.network == "BC River Forecast Centre" and snow.elev_m == 1017
    days = [d for d in snow.daily if d.depth_cm is not None]
    assert days, "expected daily depths"
    # The daily value is the reading at local midnight (07:00 UTC in daylight time,
    # 08:00 UTC after it ends).
    first = days[0]
    midnight = datetime.fromisoformat(first.date).replace(tzinfo=ZoneInfo("America/Vancouver"))
    sd = dict(data["SD"])
    assert first.depth_cm == sd[midnight.astimezone(UTC).isoformat(timespec="minutes")]
    assert snow.depth_cm is not None and snow.obs_time is not None


def test_station_without_a_depth_sensor_still_has_snow_water() -> None:
    data = bc_asws.station_slice(bc_data(), "2A06P", datetime(2026, 10, 1, tzinfo=UTC))
    snow = bc_asws.parse_station("2A06P:BC:ASWS", data, None, "America/Vancouver")
    assert snow.depth_cm is None and snow.swe_mm is not None
    assert snow.obs_time is not None  # dated from the snow-water readings
    assert any(d.swe_mm is not None for d in snow.daily)


def test_fetch_bc_once_per_run() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        name = str(req.url).rsplit("/", 1)[-1]
        return httpx.Response(200, text=(BC / name).read_text())

    with Fetcher(user_agent="t", transport=httpx.MockTransport(handler)) as f:
        out = fetch_bc(f, ["3A20P:BC:ASWS", "2A06P:BC:ASWS", None, "672:WA:SNTL"])
        assert out is not None and set(out) == {"SD", "SW", "TA"}
        assert set(out["SW"]) == {"3A20P", "2A06P"}
        assert fetch_bc(f, ["672:WA:SNTL"]) is None
    assert len(calls) == 3 and all(c.startswith(BC_DATA) for c in calls)


def test_seeded_canadian_locations_have_bc_stations() -> None:
    locs = seed()
    assert locs["whistler"].snotel == "3A20P:BC:ASWS"
    assert locs["revelstoke"].snotel == "2A06P:BC:ASWS"
    assert locs["sunshine"].snotel == "2C14P:BC:ASWS"
    assert bc_asws.is_bc(locs["whistler"].snotel) and not bc_asws.is_bc(locs["crystal"].snotel)


def test_auto_detect_picks_the_nearest_bc_station(conn: sqlite3.Connection) -> None:
    repo.save_station_rows(
        conn, bc_asws.station_rows(json.loads((BC / "stations.json").read_text()))
    )
    loc: Location = seed()["whistler"]
    mid = loc.band("mid")

    def offline(req: httpx.Request) -> httpx.Response:
        if "api.weather.gov" in str(req.url):
            return httpx.Response(404)
        return httpx.Response(
            200, json={"timezone": "America/Vancouver", "elevation": [mid.elev_m]}
        )

    with Fetcher(user_agent="t", transport=httpx.MockTransport(offline), tries=1) as f:
        out = resolve(
            conn,
            f,
            ResolveIn(
                name="Whistler",
                kind="resort",
                pins=[{"band": "mid", "lat": mid.lat, "lon": mid.lon, "elev_m": mid.elev_m}],
            ),
        )
    assert out.country == "CA"
    assert out.snotel == "3A20P:BC:ASWS"


def test_cli_fills_missing_stations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from snowwatch import cli
    from snowwatch.locations import service
    from snowwatch.settings import Settings
    from snowwatch.store.db import connect

    s = Settings(data_dir=tmp_path / "data", site_spacing_s=0)
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    assert cli.main(["init"]) == 0
    conn = connect(s.database)
    whistler = service.get_location(conn, "whistler")
    assert whistler is not None
    whistler.snotel = None
    service.upsert_location(conn, whistler, max_locations=25)
    capsys.readouterr()
    assert cli.main(["locations", "stations"]) == 0
    assert "no station list yet" in capsys.readouterr().out
    rows = bc_asws.station_rows(json.loads((BC / "stations.json").read_text()))
    repo.save_station_rows(conn, rows)
    assert cli.main(["locations", "stations"]) == 0
    assert "3A20P:BC:ASWS" in capsys.readouterr().out
    after = service.get_location(conn, "whistler")
    assert after is not None and after.snotel == "3A20P:BC:ASWS"
