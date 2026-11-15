"""Web Push alerts: subscriptions, who gets what, failures, and a real signed request."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from snowwatch import push
from snowwatch.api.app import create_app
from snowwatch.doc import Flag
from snowwatch.locations import service
from snowwatch.push import Alert, SubscribeIn
from snowwatch.settings import Settings
from snowwatch.store.db import MIGRATIONS_DIR
from tests.helpers import SEED, fixture_snapshot

PUBLIC, PRIVATE = push.generate_keys()


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def browser_keys() -> dict[str, str]:
    """A subscription's keys, as a browser would make them."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return {"p256dh": b64(point), "auth": b64(os.urandom(16))}


def sub_json(n: int = 1) -> dict[str, Any]:
    return {"endpoint": f"https://fcm.googleapis.com/fcm/send/{n}", "keys": browser_keys()}


@pytest.fixture
def on(settings: Settings) -> Settings:
    return settings.model_copy(update={"vapid_public_key": PUBLIC, "vapid_private_key": PRIVATE})


class FakeSender:
    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.sent: list[tuple[str, dict[str, str]]] = []

    def __call__(self, info: Mapping[str, Any], data: str, key: str, claims: dict[str, str]) -> int:
        assert key == PRIVATE and claims["sub"].startswith("mailto:")
        self.sent.append((str(info["endpoint"]), json.loads(data)))
        return self.status


def test_push_is_off_without_keys(settings: Settings, conn: sqlite3.Connection) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/api/push/key").status_code == 404
    body = {"subscription": sub_json()}
    assert client.post("/api/push/subscribe", json=body).status_code == 404
    assert (
        push.notify(conn, settings, {"x": ("X", [Flag(type="powder_day", severity="notice")])}) == 0
    )


def test_subscribe_test_and_unsubscribe(on: Settings, conn: sqlite3.Connection) -> None:
    app = create_app(on)
    fake = FakeSender()
    app.state.push_sender = fake
    client = TestClient(app)
    assert client.get("/api/push/key").json() == {"key": PUBLIC}
    sub = sub_json()
    r = client.post(
        "/api/push/subscribe",
        json={"subscription": sub, "locations": ["crystal"], "types": ["powder_day", "nope"]},
    )
    assert r.json()["ok"]
    (row,) = push.subscriptions(conn)
    assert row.locations == ["crystal"] and row.types == ["powder_day"]
    assert client.post("/api/push/test", json=sub).json() == {"ok": True, "sent": 1, "detail": None}
    assert fake.sent[0][1]["title"] == "Snow Watch alerts are on"
    assert client.post("/api/push/unsubscribe", json=sub).json()["ok"]
    assert push.subscriptions(conn) == []
    assert client.post("/api/push/test", json=sub).status_code == 404


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/1",  # not https
        "https://evil.example/x",  # not a push service
        "https://fcm.googleapis.com.evil.example/x",
        "https://fcm.googleapis.com:8443/x",  # odd port
        "https://user@fcm.googleapis.com/x",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_rejects_endpoints_that_are_not_push_services(on: Settings, endpoint: str) -> None:
    client = TestClient(create_app(on))
    bad = {"endpoint": endpoint, "keys": browser_keys()}
    assert client.post("/api/push/subscribe", json={"subscription": bad}).status_code == 422


def test_known_push_services_are_accepted() -> None:
    for url in (
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/abc",
        "https://api.push.apple.com/abc",
        "https://wns2-by3p.notify.windows.com/w/?token=abc",
    ):
        assert push.is_push_service(url), url


def test_saved_choices_come_back(on: Settings, conn: sqlite3.Connection) -> None:
    client = TestClient(create_app(on))
    sub = sub_json()
    choices = {"locations": ["rainy"], "types": ["wind_hold"], "units": "metric"}
    client.post("/api/push/subscribe", json={"subscription": sub, **choices})
    assert client.post("/api/push/prefs", json={"endpoint": sub["endpoint"]}).json() == choices
    missing = {"endpoint": "https://fcm.googleapis.com/fcm/send/none"}
    assert client.post("/api/push/prefs", json=missing).status_code == 404


def test_subscription_cap(on: Settings, conn: sqlite3.Connection) -> None:
    client = TestClient(create_app(on.model_copy(update={"push_max_subscriptions": 2})))
    codes = [
        client.post("/api/push/subscribe", json={"subscription": sub_json(n)}).status_code
        for n in (1, 2, 3)
    ]
    assert codes == [200, 200, 503]
    # An existing device can still update its choices.
    r = client.post("/api/push/subscribe", json={"subscription": sub_json(1), "units": "metric"})
    assert r.status_code == 200


def test_subscribe_is_rate_limited(on: Settings, conn: sqlite3.Connection) -> None:
    client = TestClient(create_app(on))
    codes = {
        client.post("/api/push/subscribe", json={"subscription": sub_json(1)}).status_code
        for _ in range(12)
    }
    assert codes == {200, 429}


def test_long_lists_are_refused(on: Settings, conn: sqlite3.Connection) -> None:
    client = TestClient(create_app(on))
    body = {"subscription": sub_json(1), "locations": [f"l{i}" for i in range(101)]}
    assert client.post("/api/push/subscribe", json=body).status_code == 422


def powder(date: str = "2026-12-05", cm: float = 23.0) -> Flag:
    return Flag(type="powder_day", severity="notice", date=date, value=cm, first_run=7)


def storm(date: str = "2026-12-04", cm: float = 40.0, severity: str = "notice") -> Flag:
    return Flag(type="storm_incoming", severity=severity, date=date, value=cm)


def alerts(*flags: Flag) -> list[Alert]:
    return [Alert(f) for f in flags]


def test_one_digest_per_subscription_with_its_types_and_locations(
    on: Settings, conn: sqlite3.Connection
) -> None:
    push.subscribe(conn, SubscribeIn.model_validate({"subscription": sub_json(1)}))
    push.subscribe(
        conn,
        SubscribeIn.model_validate(
            {"subscription": sub_json(2), "locations": ["rainy"], "units": "metric"}
        ),
    )
    wind = Flag(type="wind_hold", severity="notice", date="2026-12-04", value=80.0)
    fake = FakeSender()
    sent = push.notify(
        conn,
        on,
        {
            "crystal": ("Crystal", alerts(powder("2026-12-08"), storm(), wind)),
            "rainy": ("Rainy", alerts(storm(cm=30.0))),
        },
        fake,
    )
    assert sent == 2  # one notification each, however many locations
    by = dict(fake.sent)
    everything = by["https://fcm.googleapis.com/fcm/send/1"]
    # wind_hold isn't in the default types; the snowiest location comes first.
    assert everything["title"] == "Snow at 2 spots: Crystal 16 in from Fri"
    assert everything["body"] == (
        "Crystal: storm from Fri: 16 in in 48 h; powder day Tue, 9 in\n"
        "Rainy: storm from Fri: 12 in in 48 h"
    )
    assert everything["url"] == "/" and everything["tag"] == push.DIGEST_TAG
    rainy_only = by["https://fcm.googleapis.com/fcm/send/2"]
    assert rainy_only["title"] == "Rainy: Storm from Fri: 30 cm in 48 h"
    assert rainy_only["url"] == "/location/rainy"


def test_digest_lines_are_capped() -> None:
    items = [(f"loc{i}", f"Spot {i}", alerts(powder(cm=10.0 + i))) for i in range(6)]
    msg = push.digest(items, "metric")
    assert msg["title"] == "Powder at 6 spots: Spot 5 15 cm Sat"
    lines = msg["body"].split("\n")
    assert lines == [
        "Spot 5: powder day Sat, 15 cm",
        "Spot 4: powder day Sat, 14 cm",
        "Spot 3: powder day Sat, 13 cm",
        "+3 more",
    ]
    # Avalanche danger is a warning: it leads, and the digest is just "Alerts".
    avy = Flag(type="avalanche_danger", severity="warning", date="2026-12-05", value=4.0)
    mixed = push.digest([("a", "A", alerts(powder())), ("b", "B", alerts(avy))], "metric")
    assert mixed["title"] == "Alerts at 2 spots: B avalanche danger High"


def test_powder_day_inside_a_storm_is_folded_into_it() -> None:
    msg = push.digest(
        [("crystal", "Crystal", alerts(powder("2026-12-05"), powder("2026-12-06", 18), storm()))],
        "imperial",
    )
    assert msg["title"] == "Crystal: Storm from Fri: 16 in in 48 h (powder Sat)"
    assert msg["body"] == "Tap to see the forecast."
    up = push.digest([("c", "C", [Alert(storm(cm=60.0), was=40.0)])], "metric")
    assert up["title"] == "C: Storm from Fri, now 60 cm in 48 h"


def test_gone_subscriptions_are_removed(on: Settings, conn: sqlite3.Connection) -> None:
    push.subscribe(conn, SubscribeIn.model_validate({"subscription": sub_json(1)}))
    push.notify(conn, on, {"crystal": ("Crystal", alerts(powder()))}, FakeSender(410))
    assert push.subscriptions(conn) == []


def test_repeated_failures_remove_a_subscription(on: Settings, conn: sqlite3.Connection) -> None:
    push.subscribe(conn, SubscribeIn.model_validate({"subscription": sub_json(1)}))
    for _ in range(push.MAX_FAILURES - 1):
        push.notify(conn, on, {"crystal": ("Crystal", alerts(powder()))}, FakeSender(500))
    assert len(push.subscriptions(conn)) == 1
    push.notify(conn, on, {"crystal": ("Crystal", alerts(powder()))}, FakeSender(500))
    assert push.subscriptions(conn) == []


T0 = datetime(2026, 11, 4, 4, tzinfo=UTC)


class Runs:
    """Forecast runs for Whistler (whose forecast starts 2026-11-04), 6 h apart."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        service.import_yaml(conn, SEED, max_locations=25)
        self.conn = conn
        self.n = 0
        self.t = T0
        self.snap = fixture_snapshot("whistler").model_copy(deep=True)

    def __call__(self, *flags: Flag, after_h: float = 6) -> dict[str, list[tuple[str, Any]]]:
        self.n += 1
        self.t += timedelta(hours=after_h)
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs (id, kind, started_at, status) VALUES (?, 'full', 'x', 'ok')",
                (self.n,),
            )
            self.conn.execute(
                "INSERT INTO snapshots (location_id, run_id, created_at, doc_gz) "
                "VALUES ('whistler', ?, 'x', x'00')",
                (self.n,),
            )
        self.snap.flags = [f.model_copy() for f in flags]
        found = push.alertable_flags(
            self.conn, self.n, [("whistler", "Whistler", self.snap)], now=self.t
        )
        return {
            loc: [(a.flag.type + " " + (a.flag.date or ""), a.was) for a in al]
            for loc, (_, al) in found.items()
        }


def test_a_locations_first_forecast_alerts_nothing(conn: sqlite3.Connection) -> None:
    run = Runs(conn)
    assert run(powder("2026-11-06")) == {}
    assert run(powder("2026-11-06")) == {}  # taken as known
    assert run(powder("2026-11-06"), powder("2026-11-07")) == {
        "whistler": [("powder_day 2026-11-07", None)]
    }


def test_a_flickering_flag_alerts_once_a_day_at_most(conn: sqlite3.Connection) -> None:
    run = Runs(conn)
    run()
    p = powder("2026-11-06", 16)
    assert run(p) == {"whistler": [("powder_day 2026-11-06", None)]}
    assert run() == {}  # dropped below the threshold…
    assert run(p) == {}  # …and back within a day: the same powder day
    assert run() == {}
    assert run(p, after_h=26) == {"whistler": [("powder_day 2026-11-06", None)]}


def test_a_storm_whose_start_moves_a_day_is_the_same_storm(conn: sqlite3.Connection) -> None:
    run = Runs(conn)
    run()
    assert run(storm("2026-11-05")) == {"whistler": [("storm_incoming 2026-11-05", None)]}
    assert run(storm("2026-11-06")) == {}
    dates = [r[0] for r in conn.execute("SELECT date FROM push_log WHERE type = 'storm_incoming'")]
    assert dates == ["2026-11-06"]
    assert run(storm("2026-11-08")) == {"whistler": [("storm_incoming 2026-11-08", None)]}


def test_an_event_alerts_again_only_when_it_grows_a_lot(conn: sqlite3.Connection) -> None:
    run = Runs(conn)
    run()
    assert run(storm("2026-11-05", 30)) == {"whistler": [("storm_incoming 2026-11-05", None)]}
    assert run(storm("2026-11-05", 36)) == {}  # +20%
    assert run(storm("2026-11-05", 48)) == {"whistler": [("storm_incoming 2026-11-05", 30.0)]}
    assert run(storm("2026-11-05", 50, "warning")) == {
        "whistler": [("storm_incoming 2026-11-05", 48.0)]
    }
    assert run(storm("2026-11-05", 52, "warning")) == {}


def test_a_powder_day_inside_a_storm_already_sent_stays_quiet(conn: sqlite3.Connection) -> None:
    run = Runs(conn)
    run()
    assert run(storm("2026-11-05")) == {"whistler": [("storm_incoming 2026-11-05", None)]}
    assert run(storm("2026-11-05"), powder("2026-11-06")) == {}
    # Both new in the same run: both go (the digest folds them into one line).
    assert run(storm("2026-11-08"), powder("2026-11-09"), after_h=30) == {
        "whistler": [("storm_incoming 2026-11-08", None), ("powder_day 2026-11-09", None)]
    }


def test_only_powder_days_and_storms_within_five_days(conn: sqlite3.Connection) -> None:
    run = Runs(conn)
    run()
    far = powder("2026-11-11")  # 7 days after the forecast's first day
    assert run(far) == {}
    run.snap.days[0].date = "2026-11-06"  # two days later, it's 5 days out
    assert run(far) == {"whistler": [("powder_day 2026-11-11", None)]}
    assert run(far) == {}


def test_flags_logged_before_push_log_count_as_sent(conn: sqlite3.Connection) -> None:
    run = Runs(conn)
    run()
    with conn:
        conn.execute(
            "INSERT INTO push_log (location_id, type, date, value, severity, alerted_at, "
            "last_seen_at) VALUES ('whistler', 'powder_day', '2026-11-06', NULL, NULL, ?, ?)",
            (T0.isoformat(), T0.isoformat()),
        )
    assert run(powder("2026-11-06", 16)) == {}
    assert run(powder("2026-11-06", 30)) == {"whistler": [("powder_day 2026-11-06", 16.0)]}


def test_migration_seeds_push_log_from_flag_log(tmp_path: Path) -> None:
    from snowwatch.store.db import connect, migrate

    db = connect(tmp_path / "db.sqlite")
    names = sorted(p.stem for p in MIGRATIONS_DIR.glob("*.sql"))
    for name in names:
        if name >= "006":
            break
        db.executescript((MIGRATIONS_DIR / f"{name}.sql").read_text())
        db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        db.execute("INSERT INTO schema_migrations VALUES (?, 'x')", (name,))
    service.import_yaml(db, SEED, max_locations=25)
    with db:
        db.execute(
            "INSERT INTO runs (id, kind, started_at, status) "
            "VALUES (3, 'full', '2026-11-04T03:30:00+00:00', 'ok')"
        )
        db.executemany(
            "INSERT INTO flag_log (location_id, type, key, first_run, last_run) "
            "VALUES ('whistler', ?, ?, 3, 3)",
            [("powder_day", "2026-11-06"), ("model_outlier", "gfs")],
        )
    assert migrate(db) == ["006_push_log"]
    rows = [tuple(r) for r in db.execute("SELECT type, date, last_seen_at FROM push_log")]
    assert rows == [("powder_day", "2026-11-06", "2026-11-04T03:30:00+00:00")]


def test_avalanche_alert_once_per_day(conn: sqlite3.Connection) -> None:
    service.import_yaml(conn, SEED, max_locations=25)
    levels = {"rainy": ("Rainy", 4, "2026-12-05"), "crystal": ("Crystal", 3, "2026-12-05")}
    first = push.avalanche_alerts(conn, levels)
    assert list(first) == ["rainy"] and first["rainy"][1][0].flag.value == 4
    assert push.avalanche_alerts(conn, levels) == {}


class _Receiver(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", "0"))
        _Receiver.seen.append({"headers": dict(self.headers), "body": self.rfile.read(n)})
        self.send_response(201)
        self.end_headers()

    def log_message(self, *args: Any) -> None:
        return


@pytest.fixture
def receiver() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Receiver.seen = []
    yield f"http://127.0.0.1:{server.server_port}/push/abc"
    server.shutdown()


def test_real_encrypted_signed_request(receiver: str) -> None:
    info = {"endpoint": receiver, "keys": browser_keys()}
    status = push.webpush_sender(
        info,
        json.dumps({"title": "plaintext-marker-7f3a9c"}),
        PRIVATE,
        {"sub": "mailto:owner@example.com"},
    )
    assert status == 201
    (req,) = _Receiver.seen
    headers = {k.lower(): v for k, v in req["headers"].items()}
    assert headers["content-encoding"] == "aes128gcm"
    assert (
        headers["authorization"].startswith("vapid t=")
        and f"k={PUBLIC}" in headers["authorization"]
    )
    assert int(headers["ttl"]) > 0
    assert (
        b"plaintext-marker-7f3a9c" not in req["body"]
    )  # encrypted; long, so random bytes never match


def test_contact_prefers_an_email(on: Settings) -> None:
    assert (
        push.contact(on.model_copy(update={"contact_email": "me@example.com"}))
        == "mailto:me@example.com"
    )
    assert push.contact(
        on.model_copy(update={"contact_email": "", "nws_contact": "a b"})
    ).startswith("mailto:")
