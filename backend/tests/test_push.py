"""Web Push alerts: subscriptions, who gets what, failures, and a real signed request."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from snowwatch import push
from snowwatch.api.app import create_app
from snowwatch.doc import Flag
from snowwatch.locations import service
from snowwatch.push import SubscribeIn
from snowwatch.settings import Settings
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


def test_only_matching_types_and_locations_one_message_each(
    on: Settings, conn: sqlite3.Connection
) -> None:
    push.subscribe(conn, SubscribeIn.model_validate({"subscription": sub_json(1)}))
    push.subscribe(
        conn,
        SubscribeIn.model_validate(
            {"subscription": sub_json(2), "locations": ["rainy"], "units": "metric"}
        ),
    )
    storm = Flag(type="storm_incoming", severity="notice", date="2026-12-04", value=40.0)
    wind = Flag(type="wind_hold", severity="notice", date="2026-12-04", value=80.0)
    fake = FakeSender()
    sent = push.notify(
        conn,
        on,
        {"crystal": ("Crystal", [powder(), storm, wind]), "rainy": ("Rainy", [storm])},
        fake,
    )
    assert sent == 3
    by = {(e, m["url"]): m for e, m in fake.sent}
    crystal = by[("https://fcm.googleapis.com/fcm/send/1", "/location/crystal")]
    # wind_hold isn't in the default types; both others are in one notification.
    assert crystal["title"] == "Crystal: Powder day Sat, 9 in; storm from Fri: 16 in in 48 h"
    rainy_metric = by[("https://fcm.googleapis.com/fcm/send/2", "/location/rainy")]
    assert rainy_metric["title"] == "Rainy: Storm from Fri: 40 cm in 48 h"
    assert ("https://fcm.googleapis.com/fcm/send/2", "/location/crystal") not in by


def test_gone_subscriptions_are_removed(on: Settings, conn: sqlite3.Connection) -> None:
    push.subscribe(conn, SubscribeIn.model_validate({"subscription": sub_json(1)}))
    push.notify(conn, on, {"crystal": ("Crystal", [powder()])}, FakeSender(410))
    assert push.subscriptions(conn) == []


def test_repeated_failures_remove_a_subscription(on: Settings, conn: sqlite3.Connection) -> None:
    push.subscribe(conn, SubscribeIn.model_validate({"subscription": sub_json(1)}))
    for _ in range(push.MAX_FAILURES - 1):
        push.notify(conn, on, {"crystal": ("Crystal", [powder()])}, FakeSender(500))
    assert len(push.subscriptions(conn)) == 1
    push.notify(conn, on, {"crystal": ("Crystal", [powder()])}, FakeSender(500))
    assert push.subscriptions(conn) == []


def test_new_flags_skip_a_locations_first_run(conn: sqlite3.Connection) -> None:
    service.import_yaml(conn, SEED, max_locations=25)
    snap = fixture_snapshot("whistler").model_copy(deep=True)
    snap.flags = [powder().model_copy(update={"first_run": 2})]

    def run(run_id: int) -> None:
        with conn:
            conn.execute(
                "INSERT INTO runs (id, kind, started_at, status) VALUES (?, 'full', 'x', 'ok')",
                (run_id,),
            )
            conn.execute(
                "INSERT INTO snapshots (location_id, run_id, created_at, doc_gz) "
                "VALUES ('whistler', ?, 'x', x'00')",
                (run_id,),
            )

    run(2)
    assert push.new_flags_for_run(conn, 2, [("whistler", "Whistler", snap)]) == {}
    run(1)  # an earlier forecast exists now
    out = push.new_flags_for_run(conn, 2, [("whistler", "Whistler", snap)])
    assert list(out) == ["whistler"]
    snap.flags[0].first_run = 1  # raised before: not new
    assert push.new_flags_for_run(conn, 2, [("whistler", "Whistler", snap)]) == {}


def test_avalanche_alert_once_per_day(conn: sqlite3.Connection) -> None:
    service.import_yaml(conn, SEED, max_locations=25)
    levels = {"rainy": ("Rainy", 4, "2026-12-05"), "crystal": ("Crystal", 3, "2026-12-05")}
    first = push.avalanche_alerts(conn, levels)
    assert list(first) == ["rainy"] and first["rainy"][1][0].value == 4
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
