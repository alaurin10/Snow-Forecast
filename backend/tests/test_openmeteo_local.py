"""Self-hosted Open-Meteo (docs/OPEN-METEO-PLAN.md, milestone 1): routing, the public
fallback, the usage ledger and budget, per-host spacing, settings and the tools."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from snowwatch import checks, cli
from snowwatch.http import LOCAL_HOST, Fetcher, FetchError, fetcher_for
from snowwatch.locations import service
from snowwatch.pipeline import run_all
from snowwatch.settings import Settings
from snowwatch.sources.openmeteo import (
    ELEVATION_URL,
    ENSEMBLE_URL,
    FORECAST_URL,
    daily_weight,
    local_daily_weight,
    public_daily_weight,
)
from snowwatch.store import repo
from tests.helpers import FIXTURES, SEED, captured_at, config, fixture_transport, seed

LOCAL = "http://om.test:8080"

Handler = Callable[[httpx.Request], httpx.Response]


def ok(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"host": req.url.host})


def make(
    handler: Handler = ok, *, used: float | None = None, **kw: Any
) -> tuple[Fetcher, list[str], list[float]]:
    """A fetcher with a self-hosted server; returns it, the hosts asked and the sleeps."""
    hosts: list[str] = []
    sleeps: list[float] = []

    def record(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        return handler(req)

    f = Fetcher(
        user_agent="t",
        transport=httpx.MockTransport(record),
        sleep=sleeps.append,
        local_url=LOCAL,
        public_used=None if used is None else (lambda: used),
        **kw,
    )
    return f, hosts, sleeps


def local_down(req: httpx.Request) -> httpx.Response:
    if req.url.host == "om.test":
        raise httpx.ConnectError("connection refused")
    return ok(req)


# --- Routing -------------------------------------------------------------------------


def test_only_forecast_and_elevation_are_rewritten() -> None:
    f, hosts, _ = make()
    f.get_json(FORECAST_URL, {"latitude": "1"}, source="open-meteo", weight=6.3)
    f.get_json(ELEVATION_URL, {"latitude": "1"}, source="open-meteo")
    f.get_json(ENSEMBLE_URL, {"latitude": "1"}, source="open-meteo", weight=3.5)
    f.get_json("https://api.weather.gov/alerts", source="nws")
    assert hosts == ["om.test", "om.test", "ensemble-api.open-meteo.com", "api.weather.gov"]
    assert [c.url.split("?")[0] for c in f.calls[:2]] == [
        f"{LOCAL}/v1/forecast",
        f"{LOCAL}/v1/elevation",
    ]
    assert f.calls[0].local and f.calls[0].weight == 0
    # Only the ensemble reached a public Open-Meteo host.
    assert f.total_weight == 3.5
    assert f.local_requests == 2


def test_no_url_no_rewrite() -> None:
    hosts: list[str] = []

    def record(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        return ok(req)

    f = Fetcher(user_agent="t", transport=httpx.MockTransport(record))
    f.get_json(FORECAST_URL, source="open-meteo", weight=6.3)
    assert hosts == ["api.open-meteo.com"] and f.total_weight == 6.3


def test_local_requests_have_their_own_source_and_long_timeout() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen[req.url.host] = req.extensions["timeout"]["read"]
        return ok(req)

    f, _, _ = make(handler)
    f.get_json(FORECAST_URL, source="open-meteo")
    f.get_json(ENSEMBLE_URL, source="open-meteo")
    assert seen == {"om.test": 120.0, "ensemble-api.open-meteo.com": 40.0}
    assert set(f.sources) == {"open-meteo-local", "open-meteo"}


# --- Fallback --------------------------------------------------------------------------


def test_local_down_falls_back_to_public() -> None:
    f, hosts, _ = make(local_down, used=0.0)
    assert f.get_json(FORECAST_URL, source="open-meteo", weight=6.3) == {
        "host": "api.open-meteo.com"
    }
    assert hosts == ["om.test", "api.open-meteo.com"]
    assert f.fallbacks == 1 and f.total_weight == 6.3
    assert f.calls[-1].fallback and not f.calls[-1].local
    assert f.sources["open-meteo-local"].errors == 1
    assert f.sources["open-meteo"].ok == 1
    # While it's down, later requests go straight to the public API.
    f.get_json(FORECAST_URL, source="open-meteo", weight=6.3)
    assert hosts == ["om.test", "api.open-meteo.com", "api.open-meteo.com"]
    assert f.fallbacks == 2


def test_local_comes_back_after_a_few_minutes() -> None:
    now = [1000.0]
    f, hosts, _ = make(local_down, used=0.0, clock=lambda: now[0])
    f.get_json(FORECAST_URL, source="open-meteo")
    now[0] += 301
    f.get_json(FORECAST_URL, source="open-meteo")
    assert hosts == ["om.test", "api.open-meteo.com", "om.test", "api.open-meteo.com"]
    # A check tool can ask every time.
    g, hosts, _ = make(local_down, fallback=False, local_retry_after_s=0)
    for _ in range(2):
        with pytest.raises(FetchError, match="refused"):
            g.get_json(FORECAST_URL, source="open-meteo")
    assert hosts == ["om.test", "om.test"]


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_fall_back(status: int) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status) if req.url.host == "om.test" else ok(req)

    f, hosts, sleeps = make(handler, used=0.0)
    f.get_json(FORECAST_URL, source="open-meteo")
    assert hosts == ["om.test", "api.open-meteo.com"] and sleeps == []


def test_timeouts_fall_back() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "om.test":
            raise httpx.ReadTimeout("slow")
        return ok(req)

    f, hosts, _ = make(handler, used=0.0)
    f.get_json(FORECAST_URL, source="open-meteo")
    assert hosts == ["om.test", "api.open-meteo.com"]


def test_a_refused_request_does_not_fall_back() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "om.test":
            return httpx.Response(400, json={"error": True, "reason": "Invalid model"})
        return ok(req)

    f, hosts, _ = make(handler, used=0.0)
    with pytest.raises(FetchError, match="Invalid model"):
        f.get_json(FORECAST_URL, source="open-meteo")
    assert hosts == ["om.test"]


def test_budget_spent_means_no_fallback_and_an_error() -> None:
    f, hosts, _ = make(local_down, used=9_995.0)
    with pytest.raises(FetchError, match="budget is spent"):
        f.get_json(FORECAST_URL, source="open-meteo", weight=6.3)
    assert hosts == ["om.test"] and f.fallbacks == 0


def test_budget_counts_what_this_fetcher_spent_but_has_not_recorded() -> None:
    f, _, _ = make(local_down, used=9_990.0)
    f.get_json(FORECAST_URL, source="open-meteo", weight=6.0)  # 9,996: fits
    with pytest.raises(FetchError, match="budget is spent"):
        f.get_json(FORECAST_URL, source="open-meteo", weight=6.0)
    assert f.take_usage()["api.open-meteo.com"].weight == 6.0


def test_fallback_refused_when_the_caller_forbids_it() -> None:
    f, hosts, _ = make(local_down, used=0.0)
    with pytest.raises(FetchError, match="no public fallback"):
        f.get_json(FORECAST_URL, source="open-meteo", allow_fallback=False)
    assert hosts == ["om.test"]


def test_fallback_off_in_the_settings() -> None:
    f, hosts, _ = make(local_down, used=0.0, fallback=False)
    with pytest.raises(FetchError, match="no public fallback"):
        f.get_json(FORECAST_URL, source="open-meteo")
    assert hosts == ["om.test"]


def test_ensembles_check_the_public_budget_first() -> None:
    f, hosts, _ = make(used=9_999.0)
    with pytest.raises(FetchError, match="budget is spent"):
        f.get_json(ENSEMBLE_URL, source="open-meteo", weight=3.5)
    assert hosts == []


# --- Usage and the ledger --------------------------------------------------------------


def test_take_usage_splits_hosts_and_hands_each_request_over_once() -> None:
    f, _, _ = make(local_down, used=0.0)
    f.get_json(FORECAST_URL, source="open-meteo", weight=6.3)  # fallback
    f.get_json(ENSEMBLE_URL, source="open-meteo", weight=3.5)
    f.get_json("https://api.weather.gov/alerts", source="nws")
    u = f.take_usage()
    assert set(u) == {"api.open-meteo.com", "ensemble-api.open-meteo.com"}
    assert u["api.open-meteo.com"].fallbacks == 1 and u["api.open-meteo.com"].weight == 6.3
    assert f.take_usage() == {}
    f2, _, _ = make()
    f2.get_json(FORECAST_URL, source="open-meteo", weight=6.3)
    assert f2.take_usage()[LOCAL_HOST].requests == 1


def test_ledger_adds_up_and_resets_each_utc_day(conn: sqlite3.Connection) -> None:
    day = datetime(2026, 11, 27, 23, 30, tzinfo=UTC)
    repo.add_usage(conn, repo.utc_day(day), "ensemble-api.open-meteo.com", 70.6, 18)
    repo.add_usage(conn, repo.utc_day(day), "ensemble-api.open-meteo.com", 70.6, 18)
    repo.add_usage(conn, repo.utc_day(day), "api.open-meteo.com", 35.0, 4, fallbacks=4)
    repo.add_usage(conn, repo.utc_day(day), LOCAL_HOST, 0, 30, seconds=9.0)
    u = repo.usage_today(conn, day)
    assert u.public_weight == 176.2 and u.public_requests == 40 and u.fallbacks == 4
    assert u.local_requests == 30 and u.local_latency_s == pytest.approx(0.3)
    assert repo.usage_today(conn, day + timedelta(hours=1)).public_weight == 0


def local_fixture_transport(
    hits: list[str], *, down: bool = False, log: list[str] | None = None
) -> httpx.MockTransport:
    """The captured responses, with the self-hosted server answering forecasts."""
    inner = fixture_transport(log=log)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "om.test":
            hits.append(req.url.path)
            if down:
                raise httpx.ConnectError("connection refused")
            public = str(req.url).replace(f"{LOCAL}/v1/", "https://api.open-meteo.com/v1/")
            req = httpx.Request("GET", public)
        return inner.handle_request(req)

    return httpx.MockTransport(handler)


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    service.import_yaml(conn, SEED, max_locations=25)
    return conn


def local_run(
    conn: sqlite3.Connection, f: Fetcher, sleeps: list[float] | None = None
) -> tuple[int, Any]:
    return run_all(
        conn,
        f,
        config(),
        now=captured_at(),
        ensembles=True,
        spacing_s=0,
        sleep=(sleeps if sleeps is not None else []).append,
    )


def test_a_run_logs_public_weight_only_for_ensembles(seeded: sqlite3.Connection) -> None:
    hits: list[str] = []
    f = Fetcher(
        user_agent="t",
        transport=local_fixture_transport(hits),
        sleep=lambda s: None,
        local_url=LOCAL,
        public_used=lambda: repo.usage_today(seeded).public_weight,
    )
    sleeps: list[float] = []
    run_id, results = local_run(seeded, f, sleeps)
    assert all(r.ok for r in results) and sleeps == []  # fetched 4 at once, no pauses
    ens = sum(public_daily_weight(loc, config()) for loc in seed().values()) / 2
    weight = seeded.execute("SELECT api_weight FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
    assert weight == pytest.approx(ens, abs=0.5)
    u = repo.usage_today(seeded)
    assert set(u.by_host) == {"ensemble-api.open-meteo.com"}
    assert u.public_weight == pytest.approx(ens, abs=0.5)
    assert u.local_requests == len(hits) > 6 * 3 and u.fallbacks == 0
    # A second run adds to the same day.
    local_run(seeded, f)
    assert repo.usage_today(seeded).public_weight == pytest.approx(2 * ens, abs=1)


def test_a_run_falls_back_when_the_server_is_stopped(seeded: sqlite3.Connection) -> None:
    hits: list[str] = []
    f = Fetcher(
        user_agent="t",
        transport=local_fixture_transport(hits, down=True),
        sleep=lambda s: None,
        local_url=LOCAL,
        public_used=lambda: repo.usage_today(seeded).public_weight,
    )
    sleeps: list[float] = []
    _, results = local_run(seeded, f, sleeps)
    assert all(r.ok for r in results)
    assert len(hits) == 1  # one failed connection, then straight to the public API
    # Falling back, locations are spaced for the public API's per-minute limit again: the
    # locations already started before the server was found down (up to four at once)
    # went ahead, then one each 20 s (the test's sleeps don't pass time, so each waits
    # 20 s more than the last).
    assert 2 <= len(sleeps) <= 5
    assert [round(s / 20) for s in sleeps] == list(range(1, len(sleeps) + 1))
    u = repo.usage_today(seeded)
    assert u.fallbacks == f.fallbacks > 6 * 3 and "api.open-meteo.com" in u.by_host
    row = seeded.execute(
        "SELECT last_error, errors_today FROM source_status WHERE source = 'open-meteo-local'"
    ).fetchone()
    assert row["errors_today"] == 1 and "ConnectError" in row["last_error"]


def test_fetcher_for_reads_the_ledger(settings: Settings, conn: sqlite3.Connection) -> None:
    local = settings.model_copy(update={"open_meteo_url": LOCAL})
    f = fetcher_for(local, transport=httpx.MockTransport(local_down), sleep=lambda s: None)
    assert f.local_url == LOCAL and f.public_used is not None
    assert f.public_used() == 0.0
    repo.add_usage(conn, repo.utc_day(), "ensemble-api.open-meteo.com", 10_000, 1)
    with pytest.raises(FetchError, match="budget is spent"):
        f.get_json(FORECAST_URL, source="open-meteo", weight=1)
    # Without a server nothing is rewritten or refused.
    plain = fetcher_for(settings)
    assert plain.local_url == "" and plain.public_used is None


# --- Per-host spacing ------------------------------------------------------------------


def test_polite_hosts_get_half_a_second_between_requests() -> None:
    now = [0.0]

    def sleep(s: float) -> None:
        sleeps.append(s)
        now[0] += s

    sleeps: list[float] = []
    f = Fetcher(
        user_agent="t", transport=httpx.MockTransport(ok), sleep=sleep, clock=lambda: now[0]
    )
    f.get_json("https://api.weather.gov/a", source="nws")
    now[0] += 0.1
    f.get_json("https://api.weather.gov/b", source="nws")
    f.get_json("https://wcc.sc.egov.usda.gov/x", source="snotel")
    f.get_json("https://api.open-meteo.com/v1/forecast", source="om")
    f.get_json("https://api.open-meteo.com/v1/forecast", source="om")
    now[0] += 2
    f.get_json("https://wcc.sc.egov.usda.gov/y", source="snotel")
    assert sleeps == [pytest.approx(0.4)]


# --- Budget split and settings ---------------------------------------------------------


def test_budget_split() -> None:
    cfg = config()
    crystal = seed()["crystal"]
    ens, fc = public_daily_weight(crystal, cfg), local_daily_weight(crystal, cfg)
    assert 22 < ens < 26  # ~24 public calls per location per day
    assert 250 < fc < 320
    assert daily_weight(crystal, cfg) == pytest.approx(ens + fc, abs=0.1)


def test_settings_defaults_without_a_server(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings()
    assert not s.local_open_meteo and s.open_meteo_url == ""
    assert s.max_locations == 25 and s.site_spacing_s == 20 and s.open_meteo_fallback


def test_settings_defaults_with_a_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_METEO_URL", "http://openmeteo:8080/")
    s = Settings()
    assert s.local_open_meteo and s.open_meteo_url == "http://openmeteo:8080"
    assert s.max_locations == 50 and s.site_spacing_s == 0
    monkeypatch.setenv("MAX_LOCATIONS", "30")
    monkeypatch.setenv("SITE_SPACING_S", "5")
    s = Settings()
    assert s.max_locations == 30 and s.site_spacing_s == 5


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", site_spacing_s=0)
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    return s


def test_budget_command_shows_the_split(
    env: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["init"])
    capsys.readouterr()
    cli.main(["budget"])
    out = capsys.readouterr().out
    assert "6 active locations" in out and "ensembles: ~141 a day" in out
    local = env.model_copy(update={"open_meteo_url": LOCAL, "max_locations": 50})
    monkeypatch.setattr(cli, "get_settings", lambda: local)
    cli.main(["budget"])
    out = capsys.readouterr().out
    assert "6 of 50 active locations, about 141 of 10000 daily public" in out
    assert "~24 per location" in out and "free" in out and "used today (UTC): 0" in out


# --- Tools ---------------------------------------------------------------------------


def test_cpu_check(tmp_path: Path) -> None:
    info = tmp_path / "cpuinfo"
    info.write_text("processor : 0\nflags : fpu sse avx avx2 bmi2\n")
    assert checks.cpu_supported(info, "x86_64") == (True, "AVX2 present")
    info.write_text("processor : 0\nflags : fpu sse avx\n")
    assert checks.cpu_supported(info, "x86_64")[0] is False
    assert checks.cpu_supported(info, "aarch64") == (True, "ARM64")
    assert checks.cpu_supported(tmp_path / "missing", "x86_64")[0] is None


def meta_and_local(req: httpx.Request) -> httpx.Response:
    if req.url.host == "openmeteo.s3.amazonaws.com":
        return httpx.Response(
            200,
            json={
                "last_run_initialisation_time": 1_764_201_600,
                "last_run_availability_time": 1_764_206_000,
            },
        )
    if req.url.host == "om.test":
        return httpx.Response(200, json={"hourly": {"time": [1], "temperature_2m": [1.0]}})
    return httpx.Response(404)


def test_openmeteo_status() -> None:
    f = Fetcher(user_agent="t", transport=httpx.MockTransport(meta_and_local), tries=1)
    usage = repo.Usage(public_weight=120, fallbacks=2, local_requests=10, local_seconds=3)
    good, lines = checks.openmeteo_status(LOCAL, True, 10_000, usage, f, cpu=(True, "AVX2"))
    text = "\n".join(lines)
    assert good and "OK, " in text and "10 self-hosted requests (0.30 s each)" in text
    assert "2 fallbacks, 120 of 10000 public calls" in text
    assert "ncep_hrrr_conus  run 2025-11-27 00:00 UTC" in text
    bad, lines = checks.openmeteo_status("", True, 10_000, repo.Usage(), f, cpu=(True, "AVX2"))
    assert not bad and lines[-1] == "NOT OK"
    down = Fetcher(user_agent="t", transport=httpx.MockTransport(local_down), tries=1)
    bad, lines = checks.openmeteo_status(LOCAL, True, 10_000, usage, down, cpu=(True, "AVX2"))
    assert not bad and any("FAILED" in line for line in lines)


def test_null_share_comparison() -> None:
    local = [
        {"hourly": {"time": [1, 2, 3, 4], "a": [1, 2, 3, 4], "b": [None, 1, 2, 3]}},
        {"hourly": {"time": [1, 2, 3, 4], "a": [1, 2, 3, 4], "b": [1, 1, 2, 3]}},
    ]
    public = [
        {"hourly": {"time": [1, 2, 3, 4], "a": [1, 2, 3, 4], "b": [1, 1, 2, 3], "c": [1] * 4}},
        {"hourly": {"time": [1, 2, 3, 4], "a": [1, 2, 3, 4], "b": [1, 1, 2, 3], "c": [1] * 4}},
    ]
    na, nb, missing, differs = checks.compare_nulls(local, public)
    assert (na, nb, missing) == (2, 3, ["c"])
    assert differs == ["`b` (point 1) 25% vs 0%"]


def test_local_report_compares_with_the_fixtures() -> None:
    """The server answers like the saved public responses; the public API refuses (429)."""
    inner = fixture_transport()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "om.test":
            public = str(req.url).replace(f"{LOCAL}/v1/", "https://api.open-meteo.com/v1/")
            return inner.handle_request(httpx.Request("GET", public))
        return httpx.Response(429, json={"reason": "Daily API request limit exceeded"})

    local = Fetcher(
        user_agent="t", transport=httpx.MockTransport(handler), local_url=LOCAL, fallback=False
    )
    public = Fetcher(user_agent="t", transport=httpx.MockTransport(handler), tries=1)
    locs = [seed()["crystal"], seed()["whistler"]]
    report = checks.build_local_report(local, public, locs, config(), fixtures=FIXTURES)
    assert report.startswith(checks.LOCAL_HEADING)
    assert "| Crystal Mountain | `blend` | 18 / 18 | none | none | saved fixture |" in report
    assert "| Whistler | `upper` |" in report
    # The model check asks for more than a run does, so the fake server can't answer it.
    assert "Model check failed" in report


def test_each_check_rewrites_only_its_own_section() -> None:
    doc = "# Data source check\n\nintro\n\n## Open-Meteo\n\nold\n\n## Other endpoints\n\nx\n"
    local = f"{checks.LOCAL_HEADING}\n\nnew local\n"
    merged = checks.merge_section(doc, local)
    assert merged.endswith(local) and "old" in merged
    again = checks.merge_section(merged, f"{checks.LOCAL_HEADING}\n\nnewer\n")
    assert "new local" not in again and again.count(checks.LOCAL_HEADING) == 1
    middle = checks.merge_section(
        f"# T\n\n{checks.LOCAL_HEADING}\n\nold local\n\n## After\n\ny\n", local
    )
    assert middle == f"# T\n\n{local}\n## After\n\ny\n"
    fresh = "# Data source check\n\nfresh\n"
    assert checks.keep_section(merged, fresh) == fresh + "\n" + local
    assert checks.keep_section(doc, fresh) == fresh


# --- API -------------------------------------------------------------------------------


def test_status_meta_and_budget_with_a_server(
    settings: Settings, seeded: sqlite3.Connection
) -> None:
    from fastapi.testclient import TestClient

    from snowwatch.api.app import create_app

    password = "correct horse battery"
    local = settings.model_copy(
        update={
            "open_meteo_url": LOCAL,
            "owner_password": password,
            "static_dir": settings.data_dir / "none",
            "max_locations": 50,
        }
    )
    day = repo.utc_day()
    repo.add_usage(seeded, day, "ensemble-api.open-meteo.com", 141.2, 18)
    repo.add_usage(seeded, day, "api.open-meteo.com", 33.0, 4, fallbacks=4)
    repo.add_usage(seeded, day, LOCAL_HOST, 0, 20, seconds=6.0)
    f = Fetcher(user_agent="t", transport=httpx.MockTransport(local_down), local_url=LOCAL)
    f.get_json(FORECAST_URL, source="open-meteo")
    repo.save_source_status(seeded, f.sources)

    client = TestClient(create_app(local))
    status = client.get("/api/status").json()
    assert status["weight_today"] == 174.2
    loc = status["local"]
    assert not loc["ok"] and "ConnectError" in loc["last_error"]
    assert loc["requests_today"] == 20 and loc["latency_s"] == 0.3
    assert loc["fallbacks_today"] == 4
    assert client.get("/api/meta").json()["local_forecasts"] is True

    h = {"Origin": "http://testserver"}
    assert client.post("/api/auth/login", json={"password": password}, headers=h).is_success
    b = client.get("/api/admin/budget", headers=h).json()
    assert b["local_forecasts"] and b["max_locations"] == 50
    assert b["total"] == b["ensembles_total"] == pytest.approx(141, abs=1)
    assert b["forecasts_total"] > 1400 and b["public_used_today"] == 174.2

    # Without a server: no local card, and the budget counts everything as public.
    plain = TestClient(create_app(local.model_copy(update={"open_meteo_url": ""})))
    assert plain.get("/api/status").json()["local"] is None
    assert plain.get("/api/meta").json()["local_forecasts"] is False
