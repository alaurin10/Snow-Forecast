from __future__ import annotations

from pathlib import Path

import pytest

from snowwatch import cli
from snowwatch.scheduler import Worker, build_scheduler
from snowwatch.settings import Settings
from tests.helpers import FIXTURES, config


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", site_spacing_s=0)
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    return s


def test_init_rebuild_and_show(env: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["init"]) == 0
    assert cli.main(["init"]) == 0  # second time: seed skipped
    assert cli.main(["rebuild", "--from", str(FIXTURES)]) == 0
    capsys.readouterr()
    assert cli.main(["show", "whistler"]) == 0
    out = capsys.readouterr().out
    assert "Whistler" in out and "Next 5 days" in out and "GEPS 21" in out
    assert out.count("\n") > 25
    assert cli.main(["show", "nowhere"]) == 1


def test_budget_and_locations(
    env: Settings, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cli.main(["init"])
    capsys.readouterr()
    cli.main(["budget"])
    assert "6 active locations" in capsys.readouterr().out
    out = tmp_path / "export.yaml"
    assert cli.main(["locations", "export", str(out)]) == 0
    assert "crystal" in out.read_text()
    assert cli.main(["backup"]) == 0
    assert list(env.backup_dir.glob("snowwatch-*.db"))


def test_webcams_from_a_file_change_nothing_else(env: Settings, tmp_path: Path) -> None:
    from snowwatch.locations import service
    from snowwatch.store.db import connect

    cli.main(["init"])
    conn = connect(env.database)
    before = service.get_location(conn, "crystal")
    f = tmp_path / "webcams.yaml"
    f.write_text(
        "crystal:\n"
        "  - name: Summit 360\n"
        "    url: https://crystalmountainresort.roundshot.com/summit/\n"
        "    video_url: https://crystalmountainresort.roundshot.com/summit/\n"
        "  - name: Paradise\n"
        "    url: https://www.nps.gov/mora/learn/photosmultimedia/webcams.htm\n"
        "    image_url: https://www.nps.gov/webcams-mora/mountain.jpg\n"
        "whistler:\n"
        "  - name: Peak\n"
        "    url: https://www.whistlerblackcomb.com/\n"
        "    video_url: https://live9.brownrice.com/?sn=whistlerpeak\n"
    )
    assert cli.main(["locations", "webcams", str(f)]) == 0
    after = service.get_location(conn, "crystal")
    assert before is not None and after is not None
    assert [w.name for w in after.webcams] == ["Summit 360", "Paradise"]
    assert after.model_copy(update={"webcams": before.webcams}) == before
    whistler = service.get_location(conn, "whistler")
    assert whistler is not None
    assert whistler.webcams[0].video_url == "https://player.brownrice.com/embed/whistlerpeak"
    queued = {r["location_id"] for r in conn.execute("SELECT location_id FROM jobs")}
    assert queued == {"crystal", "whistler"}

    # One bad entry (or an unknown location) and nothing is saved.
    f.write_text("crystal: []\nnowhere: []\n")
    with pytest.raises(ValueError, match="nowhere"):
        cli.main(["locations", "webcams", str(f)])
    f.write_text("crystal: []\nwhistler:\n  - {name: X, url: 'javascript:alert(1)'}\n")
    with pytest.raises(ValueError, match="whistler"):
        cli.main(["locations", "webcams", str(f)])
    after = service.get_location(conn, "crystal")
    assert after is not None and len(after.webcams) == 2


def test_scheduler_jobs(env: Settings) -> None:
    sched = build_scheduler(Worker(env, config()))
    ids = {j.id for j in sched.get_jobs()}
    runs = [f"run-{h:02d}:30" for h in range(0, 24, 3)]
    assert {*runs, "jobs", "nightly", "weekly"} <= ids
    ens = {j.id: j.kwargs.get("ensembles") for j in sched.get_jobs() if j.id.startswith("run-")}
    assert ens == {r: r in ("run-09:30", "run-21:30") for r in runs}


def test_healthcheck_pings(env: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from snowwatch import scheduler

    pings: list[str] = []
    s = env.model_copy(
        update={
            "healthchecks_run_url": "https://hc.test/run",
            "healthchecks_backup_url": "https://hc.test/bk",
        }
    )
    w = Worker(s, config(), ping=pings.append)
    cli.main(["init"])

    class Res:
        def __init__(self, ok: bool) -> None:
            self.ok = ok

    monkeypatch.setattr(scheduler, "run_all", lambda *a, **k: (1, [Res(False)]))
    w.full_run(ensembles=False)
    assert pings == []  # nothing succeeded
    monkeypatch.setattr(scheduler, "run_all", lambda *a, **k: (2, [Res(True)]))
    w.full_run(ensembles=False)
    w.nightly()
    assert pings == ["https://hc.test/run", "https://hc.test/bk"]

    def boom(url: str) -> None:
        raise OSError("offline")

    Worker(s, config(), ping=boom).nightly()  # a failed ping never breaks the job


def test_no_ping_without_url(env: Settings) -> None:
    pings: list[str] = []
    w = Worker(env, config(), ping=pings.append)
    cli.main(["init"])
    w.nightly()
    assert pings == []


def test_worker_healthcheck(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import time

    from snowwatch import cli

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main(["healthcheck", "worker"]) == 1  # no heartbeat yet
    settings.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    settings.heartbeat_path.touch()
    assert cli.main(["healthcheck", "worker"]) == 0
    old = time.time() - 600
    os.utime(settings.heartbeat_path, (old, old))
    assert cli.main(["healthcheck", "worker"]) == 1


def test_avalanche_alerts_join_the_runs_digest(
    env: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from snowwatch import push
    from snowwatch.doc import Flag
    from snowwatch.store.db import connect

    s = env.model_copy(update={"vapid_public_key": "pub", "vapid_private_key": "priv"})
    cli.main(["init"])
    conn = connect(s.database)
    powder = push.Alert(Flag(type="powder_day", severity="notice", date="2026-12-05", value=20))
    avy = push.Alert(Flag(type="avalanche_danger", severity="warning", date="2026-12-05", value=4))
    monkeypatch.setattr(push, "alertable_flags", lambda *a, **k: {"crystal": ("Crystal", [powder])})
    calls: list[push.Found] = []
    monkeypatch.setattr(push, "notify", lambda c, st, found: calls.append(dict(found)) or 1)
    Worker(s, config())._notify(conn, 1, {"crystal": ("Crystal", [avy]), "rainy": ("Rainy", [avy])})
    (found,) = calls  # one send for the run, both kinds together
    assert [a.flag.type for a in found["crystal"][1]] == ["powder_day", "avalanche_danger"]
    assert list(found) == ["crystal", "rainy"]


def test_nwac_observations_job(
    env: Settings, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    from snowwatch import nwac_obs

    calls: list[Path] = []

    def fake_refresh(path: Path, box: object) -> object:
        calls.append(path)
        raise RuntimeError("boom")  # only logged

    monkeypatch.setattr(nwac_obs, "refresh", fake_refresh)
    cfg = config()
    w = Worker(env, cfg)
    cli.main(["init"])  # the seed has Crystal and Snoqualmie, in NWAC's area
    monkeypatch.setattr(nwac_obs, "available", lambda: False)
    w.nwac_observations()
    w.nwac_observations()
    assert calls == [] and capfd.readouterr().err.count("need Playwright") == 1
    monkeypatch.setattr(nwac_obs, "available", lambda: True)
    assert cli.main(["map", "nwac"]) == 0
    assert calls == [env.nwac_obs_path] and "NWAC observations failed" in capfd.readouterr().err
    # Not while a forecast run holds the worker's lock.
    with w.lock:
        w.nwac_observations()
    assert len(calls) == 1 and "wait for the forecast run" in capfd.readouterr().err
    off = cfg.model_copy(update={"map": cfg.map.model_copy(update={"nwac_obs": False})})
    Worker(env, off).nwac_observations()
    monkeypatch.setattr(nwac_obs, "in_area", lambda lat, lon: False)
    w.nwac_observations()
    assert len(calls) == 1
    assert "nwac_observations" in {j.id for j in build_scheduler(w).get_jobs()}
