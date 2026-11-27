"""Milestone 1b, PR 2: the app takes ensembles from the self-hosted server for fresh
systems (OPEN_METEO_ENSEMBLES=local), compares them in shadow mode, and falls back to
the public API one system at a time. `public` mode is milestone 1, whose tests in
test_openmeteo_local.py run unchanged."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from snowwatch import checks, ensembles
from snowwatch.http import Fetcher, FetchError, fetcher_for
from snowwatch.locations import service
from snowwatch.pipeline import forecast_reserve, run_all
from snowwatch.settings import Settings
from snowwatch.sources.openmeteo import (
    ENSEMBLE_MEMBERS,
    ENSEMBLE_URL,
    ensemble_request,
    public_daily_weight,
)
from snowwatch.store import repo
from tests.helpers import SEED, captured_at, config, fixture_transport, seed

LOCAL = "http://om.test:8080"
SYSTEMS = ("gfs_seamless", "ecmwf_ifs025", "gem_global")


def check(system: str, data: Any) -> str | None:
    return ensembles.response_problem(system, data, ENSEMBLE_MEMBERS[system], captured_at())


def transport(
    hits: list[str],
    *,
    down: bool = False,
    broken: tuple[str, ...] = (),
    public: list[str] | None = None,
) -> httpx.MockTransport:
    """The captured responses; the server answers forecasts and ensembles with them.
    `broken`: systems whose answer from the server has only 5 members."""
    inner = fixture_transport()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "om.test":
            hits.append(f"{req.url.path} {req.url.params.get('models', '')}")
            if down:
                raise httpx.ConnectError("connection refused")
            base = (
                "https://ensemble-api.open-meteo.com/v1/"
                if req.url.path == "/v1/ensemble"
                else "https://api.open-meteo.com/v1/"
            )
            resp = inner.handle_request(
                httpx.Request("GET", str(req.url).replace(f"{LOCAL}/v1/", base))
            )
            if req.url.params.get("models") in broken:
                data = json.loads(resp.read())
                keep = {"time", "snowfall", *[f"snowfall_member0{i}" for i in range(1, 5)]}
                data["hourly"] = {k: v for k, v in data["hourly"].items() if k in keep}
                return httpx.Response(200, json=data)
            return resp
        if public is not None and "open-meteo.com" in str(req.url.host):
            public.append(f"{req.url.path} {req.url.params.get('models', '')}")
        return inner.handle_request(req)

    return httpx.MockTransport(handler)


def make(
    mode: str,
    hits: list[str],
    *,
    stale: dict[str, str] | None = None,
    used: float | None = None,
    **kw: Any,
) -> Fetcher:
    stale = stale or {}
    return Fetcher(
        user_agent="t",
        transport=kw.pop("transport", None) or transport(hits, **kw),
        sleep=lambda s: None,
        local_url=LOCAL,
        public_used=None if used is None else (lambda: used),
        ensemble_mode=mode,
        ensemble_stale=lambda s: stale.get(s),
        ensemble_check=check,
    )


def ens(f: Fetcher, system: str, **kw: Any) -> Any:
    req = ensemble_request(seed()["crystal"], system)
    return f.get_json(req.url, req.params, source=req.source, weight=req.weight, **kw)


# --- Routing ---------------------------------------------------------------------------


def test_local_mode_routes_only_fresh_systems() -> None:
    hits: list[str] = []
    public: list[str] = []
    f = make("local", hits, stale={"ecmwf_ifs025": "run 30 h old"}, public=public)
    for system in SYSTEMS:
        ens(f, system)
    assert hits == ["/v1/ensemble gfs_seamless", "/v1/ensemble gem_global"]
    assert public == ["/v1/ensemble ecmwf_ifs025"]  # the stale one, on its own
    assert f.ensembles_local == {"gfs_seamless", "gem_global"}
    assert f.ensembles_public == {"ecmwf_ifs025": "run 30 h old"}
    assert f.total_weight == ensemble_request(seed()["crystal"], "ecmwf_ifs025").weight


@pytest.mark.parametrize("mode", ["public", "shadow"])
def test_other_modes_never_route_ensembles(mode: str) -> None:
    hits: list[str] = []
    f = make(mode, hits)
    for system in SYSTEMS:
        ens(f, system)
    assert hits == [] and not f.ensembles_local


def test_no_server_means_public_whatever_the_setting() -> None:
    f = Fetcher(user_agent="t", ensemble_mode="local", ensemble_stale=lambda s: None)
    assert f.ensemble_mode == "public" and not f.local_ensemble("gem_global")


def test_an_unusable_answer_falls_back_on_its_own() -> None:
    hits: list[str] = []
    public: list[str] = []
    f = make("local", hits, broken=("gem_global",), public=public)
    data = ens(f, "gem_global")
    assert ensembles.members_with_data(data) == 21  # the public answer
    assert public == ["/v1/ensemble gem_global"]
    assert "5 of 21 members" in f.ensembles_public["gem_global"]
    assert f.fallbacks == 0  # forecasts aren't falling back
    assert f.calls[-1].fallback  # but this request is a fallback in the ledger
    ens(f, "gfs_seamless")
    assert f.ensembles_local == {"gfs_seamless"}


def test_a_short_reach_counts_as_a_failure() -> None:
    data = json.loads(
        httpx.MockTransport(fixture_transport().handle_request)
        .handle_request(
            httpx.Request(
                "GET",
                httpx.URL(
                    ENSEMBLE_URL,
                    params=ensemble_request(seed()["crystal"], "gem_global").params,
                ),
            )
        )
        .read()
    )
    assert check("gem_global", data) is None
    later = captured_at() + timedelta(hours=48)
    why = ensembles.response_problem("gem_global", data, 21, later)
    assert why is not None and "h ahead, not 360" in why
    assert "0 of 21 members" in str(ensembles.response_problem("gem_global", {}, 21))


def test_ensembles_fall_back_even_with_forecast_fallback_off() -> None:
    hits: list[str] = []
    f = make("local", hits, down=True)
    f.fallback = False
    ens(f, "gem_global")  # public, as ensembles always were
    with pytest.raises(FetchError, match="no public fallback here"):
        ens(f, "gem_global", allow_fallback=False)


# --- The fallback order ----------------------------------------------------------------


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    service.import_yaml(conn, SEED, max_locations=25)
    return conn


def run(conn: sqlite3.Connection, f: Fetcher, *, ensembles_now: bool | None) -> list[Any]:
    _, results = run_all(
        conn,
        f,
        config(),
        now=captured_at(),
        ensembles=ensembles_now,
        spacing_s=0,
        sleep=lambda s: None,
    )
    return results


def ens_rows(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    return {(r[0], r[1]) for r in conn.execute("SELECT location_id, system FROM ensemble_cache")}


def test_fresh_systems_are_read_every_run_for_free(seeded: sqlite3.Connection) -> None:
    hits: list[str] = []
    public: list[str] = []
    f = make("local", hits, public=public)
    results = run(seeded, f, ensembles_now=False)  # not an ensemble run on the schedule
    assert all(r.ok for r in results)
    assert sum("/v1/ensemble" in h for h in hits) == 6 * 3
    assert not any("ensemble" in p for p in public)
    assert repo.usage_today(seeded, captured_at()).public_weight == 0
    assert len(ens_rows(seeded)) == 6 * 3  # cached, for a short outage
    states = repo.ensemble_states(seeded)
    assert {s: v.local for s, v in states.items()} == dict.fromkeys(SYSTEMS, True)


def test_outage_uses_the_cache_then_the_public_schedule(seeded: sqlite3.Connection) -> None:
    # A first run fills the cache from the server.
    run(seeded, make("local", []), ensembles_now=False)
    # The downloader stalls: GEFS goes stale. Between public ensemble runs, the cache.
    public: list[str] = []
    stale = {"gfs_seamless": "its newest run is 30 h old"}
    run(seeded, make("local", [], stale=stale, public=public), ensembles_now=False)
    assert "/v1/ensemble gfs_seamless" not in public
    # On the public schedule's ensemble run, the public API, for GEFS alone.
    public.clear()
    hits: list[str] = []
    run(seeded, make("local", hits, stale=stale, public=public), ensembles_now=True)
    assert sorted({p for p in public if "ensemble" in p}) == ["/v1/ensemble gfs_seamless"]
    assert "/v1/ensemble gfs_seamless" not in hits
    state = repo.ensemble_states(seeded)["gfs_seamless"]
    assert not state.local and state.reason == "its newest run is 30 h old"
    assert repo.ensemble_states(seeded)["gem_global"].local


def test_a_failed_server_read_uses_the_cache_before_the_public_api(
    seeded: sqlite3.Connection,
) -> None:
    run(seeded, make("local", []), ensembles_now=False)
    public: list[str] = []
    results = run(seeded, make("local", [], broken=SYSTEMS, public=public), ensembles_now=False)
    assert all(r.ok for r in results)
    assert not any("ensemble" in p for p in public)  # the cache covered it
    snap = repo.latest_snapshot(seeded, "crystal")
    assert snap is not None and not any("ens_" in w for w in snap.warnings)


def test_nothing_cached_goes_to_the_public_api(seeded: sqlite3.Connection) -> None:
    public: list[str] = []
    run(seeded, make("local", [], broken=("gem_global",), public=public), ensembles_now=False)
    assert sum("gem_global" in p for p in public) == 6


def test_reserve_for_forecasts_when_the_whole_server_is_down(
    seeded: sqlite3.Connection,
) -> None:
    locs = service.list_locations(seeded)
    # The fixtures were captured at 21:35 UTC: this run is the day's last, so the reserve
    # is one run's blend and multi-model requests.
    reserve = forecast_reserve(locs, config(), captured_at())
    assert reserve > 100
    # Today's public use leaves just the reserve: the required forecasts still go, while
    # ensembles and the other optional requests don't.
    used = 10_000 - reserve - 0.5
    public: list[str] = []
    f = make("local", [], down=True, public=public, used=used)
    results = run(seeded, f, ensembles_now=True)
    assert all(r.ok for r in results)
    assert any("/v1/forecast" in p for p in public)
    assert not any("ensemble" in p for p in public)
    snap = repo.latest_snapshot(seeded, "crystal")
    assert snap is not None and any("budget is spent" in w for w in snap.warnings)
    # In public mode there's no reserve: milestone 1 exactly.
    seeded.execute("DELETE FROM ensemble_cache")
    public.clear()
    f = make("public", [], down=True, public=public, used=used)
    run(seeded, f, ensembles_now=True)
    assert any("ensemble" in p for p in public)


def test_reserve_counts_the_rest_of_the_day(seeded: sqlite3.Connection) -> None:
    locs = service.list_locations(seeded)
    morning = forecast_reserve(locs, config(), datetime(2026, 11, 27, 0, 40, tzinfo=UTC))
    evening = forecast_reserve(locs, config(), datetime(2026, 11, 27, 21, 40, tzinfo=UTC))
    assert morning == pytest.approx(evening * 8, abs=1)  # 7 more runs, plus this one


# --- Budget ----------------------------------------------------------------------------


def _meta(data: Path, folder: str, init: datetime) -> None:
    p = data / folder / "static" / "meta.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"last_run_initialisation_time": init.timestamp()}))


def test_budget_with_local_ensembles(tmp_path: Path) -> None:
    loc, cfg = seed()["crystal"], config()
    full = public_daily_weight(loc, cfg)
    assert public_daily_weight(loc, cfg, cfg.ensembles) == 0
    gefs = ensemble_request(loc, "gfs_seamless").weight * len(cfg.schedule.ensemble_runs_utc)
    assert public_daily_weight(loc, cfg, ["gfs_seamless"]) == pytest.approx(full - gefs, abs=0.1)

    now = datetime.now(UTC)
    for folder in ("ncep_gefs025", "ncep_gefs05", "cmc_gem_geps"):
        _meta(tmp_path, folder, now - timedelta(hours=8))
    _meta(tmp_path, "ecmwf_ifs025_ensemble", now - timedelta(hours=20))
    s = Settings(open_meteo_url=LOCAL, open_meteo_data_dir=tmp_path, open_meteo_ensembles="local")
    assert ensembles.local_systems(s, cfg.ensembles) == ["gfs_seamless", "gem_global"]
    shadow = s.model_copy(update={"open_meteo_ensembles": "shadow"})
    assert ensembles.local_systems(shadow, cfg.ensembles) == []


def test_settings() -> None:
    assert Settings().ensemble_mode == "public"
    assert Settings(open_meteo_ensembles="LOCAL").ensemble_mode == "public"  # no server
    assert Settings(open_meteo_url=LOCAL, open_meteo_ensembles="Local").ensemble_mode == "local"
    with pytest.raises(ValueError):
        Settings(open_meteo_ensembles="sometimes")


# --- Freshness -------------------------------------------------------------------------


def test_freshness_per_system(tmp_path: Path) -> None:
    now = datetime(2026, 11, 27, 12, tzinfo=UTC)
    assert ensembles.stale_reason(tmp_path, "gem_global", now) == "no run downloaded"
    assert ensembles.stale_reason(tmp_path, "icon_seamless", now) == "not downloaded here"
    _meta(tmp_path, "cmc_gem_geps", now - timedelta(hours=25))
    assert ensembles.stale_reason(tmp_path, "gem_global", now) is None  # GEPS: 26 h
    _meta(tmp_path, "cmc_gem_geps", now - timedelta(hours=27))
    assert "27 h old, more than 26" in str(ensembles.stale_reason(tmp_path, "gem_global", now))
    # GEFS is two downloads: the older one counts.
    _meta(tmp_path, "ncep_gefs025", now - timedelta(hours=6))
    assert ensembles.stale_reason(tmp_path, "gfs_seamless", now) == "no run downloaded"
    _meta(tmp_path, "ncep_gefs05", now - timedelta(hours=15))
    assert "15 h old, more than 14" in str(ensembles.stale_reason(tmp_path, "gfs_seamless", now))
    assert ensembles.local_run(tmp_path, "gfs_seamless") == now - timedelta(hours=15)


# --- Shadow mode -----------------------------------------------------------------------


def test_shadow_records_each_public_ensemble(seeded: sqlite3.Connection) -> None:
    hits: list[str] = []
    public: list[str] = []
    f = make("shadow", hits, public=public)
    init = captured_at().replace(hour=0, minute=0, second=0, microsecond=0)
    f.ensemble_run = lambda system: init
    results = run(seeded, f, ensembles_now=True)
    assert all(r.ok for r in results)
    assert sum("ensemble" in p for p in public) == 6 * 3  # the app still uses public
    assert sum("/v1/ensemble" in h for h in hits) == 6 * 3  # and asks the server too
    rows = seeded.execute("SELECT * FROM ensemble_shadow").fetchall()
    assert len(rows) == 18
    row = next(r for r in rows if r["system"] == "ecmwf_ifs025")
    assert row["members_local"] == row["members_public"] == 51
    assert row["mean_diff_cm"] == 0 and row["max_diff_cm"] == 0  # same answers here
    assert row["local_run"] == init.isoformat()
    # The public data's run (from the bucket) isn't in the fixtures: not counted as same.
    summary = {s.system: s for s in repo.shadow_summary(seeded, now=captured_at())}
    assert summary["ecmwf_ifs025"].comparisons == 6 and summary["ecmwf_ifs025"].same_run == 0
    assert summary["ecmwf_ifs025"].mean_diff_cm is None
    seeded.execute("UPDATE ensemble_shadow SET public_run = local_run")
    summary = {s.system: s for s in repo.shadow_summary(seeded, now=captured_at())}
    assert summary["gem_global"].same_run == 6 and summary["gem_global"].max_diff_cm == 0
    # Only public ensemble fetches are shadowed: none on a run that uses the cache.
    run(seeded, make("shadow", []), ensembles_now=False)
    assert seeded.execute("SELECT COUNT(*) FROM ensemble_shadow").fetchone()[0] == 18


def test_shadow_records_a_server_failure(seeded: sqlite3.Connection) -> None:
    run(seeded, make("shadow", [], down=True), ensembles_now=True)
    row = seeded.execute("SELECT * FROM ensemble_shadow LIMIT 1").fetchone()
    assert "connection refused" in row["error"]
    assert row["members_local"] is None


def test_comparison() -> None:
    now = datetime(2026, 11, 27, tzinfo=UTC)
    t = [now.timestamp() + 3600 * i for i in range(400)]
    a = {"hourly": {"time": t, "snowfall": [1.0] * 400, "snowfall_member01": [0.5] * 400}}
    b = {
        "hourly": {
            "time": t,
            "snowfall": [1.0] * 390 + [None] * 10,
            "snowfall_member01": [0.4] * 400,
        }
    }
    c = ensembles.compare(a, b, now)
    assert c.members_local == c.members_public == 2
    assert c.reach_local_h == 399 and c.reach_public_h == 389  # the shortest member
    assert c.max_diff_cm == pytest.approx(40, abs=0.01)  # 400 h x 0.1 cm
    assert c.mean_diff_cm == pytest.approx(25, abs=0.01)  # (10 + 40) / 2


def test_public_run_from_the_bucket() -> None:
    t = datetime(2026, 11, 27, 6, tzinfo=UTC)
    metas = {
        "ncep_gefs025": {"last_run_initialisation_time": t.timestamp()},
        "ncep_gefs05": {"last_run_initialisation_time": (t - timedelta(hours=6)).timestamp()},
    }

    def get(url: str) -> Any:
        return metas[url.split("/data/")[1].split("/")[0]]

    assert ensembles.public_run(get, "gfs_seamless") == t - timedelta(hours=6)
    assert ensembles.public_run(lambda url: {}, "gem_global") is None


# --- Status, budget and checks -----------------------------------------------------------


def test_status_and_budget_with_local_ensembles(
    settings: Settings, seeded: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from snowwatch.api.app import create_app

    now = datetime.now(UTC)
    vol = tmp_path / "vol"
    for folder in ("ncep_gefs025", "ncep_gefs05", "ecmwf_ifs025_ensemble", "cmc_gem_geps"):
        _meta(vol, folder, now - timedelta(hours=8))
    s = settings.model_copy(
        update={
            "open_meteo_url": LOCAL,
            "open_meteo_data_dir": vol,
            "open_meteo_ensembles": "local",
            "owner_password": "correct horse battery",
        }
    )
    stamp = now.isoformat(timespec="seconds")
    repo.update_ensemble_state(seeded, "gem_global", False, "5 of 21 members", stamp)
    repo.save_shadow(
        seeded,
        1,
        [repo.ShadowRow("crystal", "gem_global", stamp, stamp, stamp, 21, 21, 370, 372, 0.4, 1.2)],
    )
    client = TestClient(create_app(s))
    out = client.get("/api/status").json()["ensembles"]
    assert out["mode"] == "local"
    by = {r["system"]: r for r in out["systems"]}
    assert by["gfs_seamless"]["source"] == "self-hosted" and by["gfs_seamless"]["age_h"] == 8
    assert by["gem_global"]["source"] == "public"
    assert by["gem_global"]["reason"] == "5 of 21 members" and by["gem_global"]["since"] == stamp
    assert out["shadow"][0] == {
        "system": "gem_global",
        "label": "GEPS",
        "comparisons": 1,
        "errors": 0,
        "same_run": 1,
        "members_local_min": 21,
        "members_public_max": 21,
        "reach_gap_h": 2.0,
        "mean_diff_cm": 0.4,
        "max_diff_cm": 1.2,
    }
    assert client.get("/api/status").json()["local"] is not None
    # Without a server, no ensembles block.
    assert TestClient(create_app(settings)).get("/api/status").json()["ensembles"] is None


def test_budget_command_with_local_ensembles(
    settings: Settings,
    seeded: sqlite3.Connection,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from snowwatch import cli

    now = datetime.now(UTC)
    for folder in ("ncep_gefs025", "ncep_gefs05", "ecmwf_ifs025_ensemble", "cmc_gem_geps"):
        _meta(tmp_path, folder, now - timedelta(hours=8))
    s = settings.model_copy(
        update={
            "open_meteo_url": LOCAL,
            "open_meteo_data_dir": tmp_path,
            "open_meteo_ensembles": "local",
        }
    )
    assert cli.cmd_budget(None, s) == 0  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "about 0 of 10000 daily public" in out
    assert "ensembles: self-hosted (GEFS, ECMWF ENS, GEPS), every run, free" in out


def test_status_lines_show_where_ensembles_come_from(tmp_path: Path) -> None:
    _, lines = ensembles.status_lines(
        tmp_path,
        mode="local",
        sources={"gem_global": (False, "5 of 21 members", "2026-11-27T10:00:00+00:00")},
    )
    text = "\n".join(lines)
    assert "the server for fresh systems, else the public API (local)" in text
    assert "GEPS           PUBLIC API (5 of 21 members) since 2026-11-27T10:00:00+00:00" in text


def test_snapshot_differences_fold_list_positions() -> None:
    a = {"windows": [{"ens": {"p90": 10.0, "n": 21}}, {"ens": {"p90": 5.0, "n": 21}}], "x": "a"}
    b = {"windows": [{"ens": {"p90": 10.5, "n": 21}}, {"ens": {"p90": 7.0, "n": 20}}], "x": "a"}
    diffs = checks.snapshot_differences(a, b)
    assert [(f, n) for f, n, _, _ in diffs] == [("windows[].ens.n", 1), ("windows[].ens.p90", 2)]
    p90 = next(d for d in diffs if d[0].endswith("p90"))
    assert p90[2] == 2.0 and p90[3] == "windows[1].ens.p90: 5.0 vs 7.0"
    assert checks._over("windows[].ens.n", 1) and checks._over("windows[].ens.p90", 2.0)
    assert not checks._over("windows[].ens.p90", 0.5)


def test_check_ensembles_on_the_fixtures(seeded: sqlite3.Connection) -> None:
    f = make("public", [])
    init = captured_at().replace(hour=0, minute=0, second=0, microsecond=0)
    f.ensemble_run = lambda system: init
    locs = [seed()["crystal"]]
    ok, report = checks.check_ensembles(f, locs, config(), now=captured_at())
    # The server answers with the same captured responses: nothing differs.
    assert ok, report
    assert "### Crystal Mountain" in report and "0 fields differ, 0 flagged" in report
    assert "runs unknown" in report  # the public bucket isn't in the fixtures


def test_fetcher_for_wires_the_volume(settings: Settings, tmp_path: Path) -> None:
    now = datetime.now(UTC)
    _meta(tmp_path, "cmc_gem_geps", now - timedelta(hours=3))
    s = settings.model_copy(
        update={
            "open_meteo_url": LOCAL,
            "open_meteo_data_dir": tmp_path,
            "open_meteo_ensembles": "local",
        }
    )
    f = fetcher_for(s)
    assert f.ensemble_mode == "local"
    assert f.local_ensemble("gem_global") and not f.local_ensemble("gfs_seamless")
    assert f.ensembles_public["gfs_seamless"] == "no run downloaded"
    assert f.ensemble_run is not None and f.ensemble_run("gem_global") is not None
