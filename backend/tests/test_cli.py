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


def test_scheduler_jobs(env: Settings) -> None:
    sched = build_scheduler(Worker(env, config()))
    ids = {j.id for j in sched.get_jobs()}
    assert {"run-03:30", "run-09:30", "run-15:30", "run-21:30", "jobs", "nightly", "weekly"} <= ids
    ens = {j.id: j.kwargs.get("ensembles") for j in sched.get_jobs() if j.id.startswith("run-")}
    assert ens == {"run-03:30": False, "run-09:30": True, "run-15:30": False, "run-21:30": True}


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
