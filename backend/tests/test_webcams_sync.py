"""config/webcams.yaml applies itself: only entries that changed, never losing edits made
on the Manage page to a location the file hasn't changed."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from snowwatch.config import ForecastConfig
from snowwatch.locations import service
from snowwatch.models import Webcam
from snowwatch.scheduler import Worker
from snowwatch.settings import Settings
from tests.conftest import make_location

CAM_A = "  - {name: A, url: 'https://a.example/', image_url: 'https://a.example/a.jpg'}\n"
CAM_B = "  - {name: B, url: 'https://b.example/'}\n"
MANUAL = Webcam(name="Mine", url="https://mine.example/")


def add(conn: sqlite3.Connection, loc_id: str, webcams: list[Webcam] | None = None) -> None:
    loc = make_location(id=loc_id, name=loc_id, webcams=webcams or [])
    service.upsert_location(conn, loc, max_locations=25)


def names(conn: sqlite3.Connection, loc_id: str) -> list[str]:
    loc = service.get_location(conn, loc_id)
    assert loc is not None
    return [w.name for w in loc.webcams]


def test_applies_new_and_changed_entries_only(conn: sqlite3.Connection, tmp_path: Path) -> None:
    add(conn, "hill")
    f = tmp_path / "webcams.yaml"
    f.write_text("hill:\n" + CAM_A)
    assert service.sync_webcams_yaml(conn, f).applied == {"hill": 1}
    assert names(conn, "hill") == ["A"]

    # Unchanged file: nothing to do, and an edit on the Manage page stays.
    loc = service.get_location(conn, "hill")
    assert loc is not None
    service.upsert_location(conn, loc.model_copy(update={"webcams": [MANUAL]}), max_locations=25)
    res = service.sync_webcams_yaml(conn, f)
    assert res.applied == {} and res.kept == []
    assert names(conn, "hill") == ["Mine"]

    # The file's entry changes: it applies, replacing the edit.
    f.write_text("hill:\n" + CAM_A + CAM_B)
    assert service.sync_webcams_yaml(conn, f).applied == {"hill": 2}
    assert names(conn, "hill") == ["A", "B"]


def test_first_sight_keeps_a_locations_own_webcams(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Starting on an installation whose webcams were already set: nothing is overwritten."""
    add(conn, "edited", [MANUAL])
    add(conn, "same")
    f = tmp_path / "webcams.yaml"
    f.write_text("same:\n" + CAM_A)
    service.sync_webcams_yaml(conn, f)  # "same" now matches the file
    f.write_text("edited:\n" + CAM_A + "same:\n" + CAM_A)
    with conn:
        conn.execute("DELETE FROM webcams_applied")  # as if the feature had just arrived
    res = service.sync_webcams_yaml(conn, f)
    assert res.applied == {} and res.kept == ["edited"]
    assert names(conn, "edited") == ["Mine"] and names(conn, "same") == ["A"]
    # Once the entry changes, it applies there too.
    f.write_text("edited:\n" + CAM_B + "same:\n" + CAM_A)
    assert service.sync_webcams_yaml(conn, f).applied == {"edited": 1}


def test_waits_for_a_location_and_skips_bad_entries(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    add(conn, "hill")
    f = tmp_path / "webcams.yaml"
    f.write_text(
        "later:\n" + CAM_A + "bad:\n  - {name: X, url: 'javascript:alert(1)'}\nhill:\n" + CAM_B
    )
    res = service.sync_webcams_yaml(conn, f)
    assert res.applied == {"hill": 1} and res.waiting == ["later"] and list(res.invalid) == ["bad"]
    add(conn, "later")  # added on the Manage page
    assert service.sync_webcams_yaml(conn, f).applied == {"later": 1}
    assert names(conn, "later") == ["A"]


def test_missing_file_is_nothing_to_do(conn: sqlite3.Connection, tmp_path: Path) -> None:
    res = service.sync_webcams_yaml(conn, tmp_path / "none.yaml")
    assert res == service.WebcamSync()


def test_the_command_counts_as_applied(conn: sqlite3.Connection, tmp_path: Path) -> None:
    """After `snowwatch locations webcams`, the worker has nothing left to apply."""
    add(conn, "hill", [MANUAL])
    f = tmp_path / "webcams.yaml"
    f.write_text("hill:\n" + CAM_A)
    assert service.set_webcams_yaml(conn, f) == {"hill": 1}
    loc = service.get_location(conn, "hill")
    assert loc is not None
    service.upsert_location(conn, loc.model_copy(update={"webcams": [MANUAL]}), max_locations=25)
    assert service.sync_webcams_yaml(conn, f).applied == {}
    assert names(conn, "hill") == ["Mine"]


def test_worker_applies_and_refreshes(
    settings: Settings,
    cfg: ForecastConfig,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "webcams.yaml").write_text("hill:\n" + CAM_A + "later:\n" + CAM_B)
    s = settings.model_copy(update={"config_dir": config_dir})
    worker = Worker(s, cfg)
    from snowwatch.store.db import connect

    conn = connect(s.database)
    add(conn, "hill")
    with caplog.at_level(logging.INFO, logger="snowwatch"):
        worker.sync_webcams()
        worker.sync_webcams()
    assert names(conn, "hill") == ["A"]
    queued = [r["location_id"] for r in conn.execute("SELECT location_id FROM jobs")]
    assert queued == ["hill"]
    # The waiting location is mentioned once, not on every pass.
    assert sum("not added yet" in r.getMessage() for r in caplog.records) == 1
