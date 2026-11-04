from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from snowwatch.locations import service
from tests.conftest import SEED, make_location


def test_upsert_get_and_update(conn: sqlite3.Connection) -> None:
    loc = make_location()
    service.upsert_location(conn, loc, max_locations=5)
    assert service.get_location(conn, "testhill") == loc
    service.upsert_location(conn, loc.model_copy(update={"name": "Renamed"}), max_locations=5)
    got = service.get_location(conn, "testhill")
    assert got is not None and got.name == "Renamed"
    assert len(service.list_locations(conn)) == 1


def test_list_is_ordered_and_hides_paused_and_archived(conn: sqlite3.Connection) -> None:
    service.upsert_location(conn, make_location(id="bbb", sort_order=1), max_locations=5)
    service.upsert_location(conn, make_location(id="aaa", sort_order=2), max_locations=5)
    service.upsert_location(conn, make_location(id="ccc", active=False), max_locations=5)
    assert [x.id for x in service.list_locations(conn)] == ["bbb", "aaa"]
    assert [x.id for x in service.list_locations(conn, include_inactive=True)] == [
        "ccc",
        "bbb",
        "aaa",
    ]
    service.set_order(conn, ["aaa", "bbb"])
    assert [x.id for x in service.list_locations(conn)] == ["aaa", "bbb"]
    service.archive_location(conn, "aaa")
    assert [x.id for x in service.list_locations(conn)] == ["bbb"]
    assert len(service.list_locations(conn, include_inactive=True, include_archived=True)) == 3


def test_active_cap(conn: sqlite3.Connection) -> None:
    service.upsert_location(conn, make_location(id="one"), max_locations=2)
    service.upsert_location(conn, make_location(id="two"), max_locations=2)
    with pytest.raises(service.LocationLimitError):
        service.upsert_location(conn, make_location(id="three"), max_locations=2)
    # Paused locations don't count, and updating an existing one is fine.
    service.upsert_location(conn, make_location(id="three", active=False), max_locations=2)
    service.upsert_location(conn, make_location(id="two", name="Two"), max_locations=2)


def test_yaml_import_export_round_trip(conn: sqlite3.Connection, tmp_path: Path) -> None:
    assert service.import_yaml(conn, SEED, max_locations=25) == 6
    text = service.export_yaml(conn)
    out = tmp_path / "export.yaml"
    out.write_text(text)
    assert service.load_yaml(out) == service.load_yaml(SEED)


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    item = make_location().model_dump(mode="json")
    path = tmp_path / "dup.yaml"
    path.write_text(yaml.safe_dump([item, item]))
    with pytest.raises(ValueError, match="duplicate"):
        service.load_yaml(path)
