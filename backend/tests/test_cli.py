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
