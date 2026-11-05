"""Phone and desktop alerts through the W3C Web Push API.

The browser subscribes with our VAPID public key and hands us an endpoint at its
push service (Google, Apple or Mozilla). We encrypt a small JSON payload for
that subscription and POST it there; the service worker shows it. Push is off
until VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are set (`snowwatch push keys`).

Alerts go out when a flag is first raised for a location (never on a
location's very first run, which would raise everything at once), at most one
notification per location per run.
"""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from snowwatch.doc import Flag, Snapshot
from snowwatch.settings import Settings
from snowwatch.store.db import utcnow_iso

log = logging.getLogger("snowwatch.push")

ALERT_TYPES = ("powder_day", "storm_incoming", "wind_hold", "avalanche_danger")
DEFAULT_TYPES = ["powder_day", "storm_incoming"]
MAX_FAILURES = 5


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscription(BaseModel):
    """What `PushManager.subscribe()` returns (its toJSON())."""

    endpoint: str = Field(pattern=r"^https://")
    keys: SubscriptionKeys


class SubscribeIn(BaseModel):
    subscription: PushSubscription
    locations: list[str] = []  # empty = every location
    types: list[str] = DEFAULT_TYPES
    units: str = Field(default="imperial", pattern=r"^(imperial|metric)$")


class PushOut(BaseModel):
    ok: bool
    sent: int = 0
    detail: str | None = None


# --- keys --------------------------------------------------------------------


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def generate_keys() -> tuple[str, str]:
    """A new VAPID key pair: (public key for the browser, private key), base64url."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from py_vapid import Vapid01

    v = Vapid01()
    v.generate_keys()
    raw = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    public = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return _b64(public), _b64(raw)


def contact(settings: Settings) -> str:
    """The VAPID "sub" claim: how a push service can reach the sender (an email)."""
    for candidate in [*settings.admin_email_list, settings.nws_contact]:
        if candidate and "@" in candidate and " " not in candidate.strip():
            return f"mailto:{candidate.strip()}"
    return "mailto:snowwatch@example.com"


def enabled(settings: Settings) -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


# --- subscriptions -------------------------------------------------------------


def subscribe(conn: sqlite3.Connection, body: SubscribeIn, email: str | None) -> None:
    types = [t for t in body.types if t in ALERT_TYPES] or DEFAULT_TYPES
    with conn:
        conn.execute(
            "INSERT INTO push_subs (endpoint, keys_json, email, units, locations_json, "
            "types_json, created_at, fail_count) VALUES (?, ?, ?, ?, ?, ?, ?, 0) "
            "ON CONFLICT (endpoint) DO UPDATE SET keys_json = excluded.keys_json, "
            "email = excluded.email, units = excluded.units, "
            "locations_json = excluded.locations_json, types_json = excluded.types_json, "
            "fail_count = 0",
            (
                body.subscription.endpoint,
                body.subscription.keys.model_dump_json(),
                email,
                body.units,
                json.dumps(body.locations),
                json.dumps(types),
                utcnow_iso(),
            ),
        )


def unsubscribe(conn: sqlite3.Connection, endpoint: str) -> bool:
    with conn:
        return conn.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,)).rowcount > 0


@dataclass
class Sub:
    endpoint: str
    keys: dict[str, str]
    units: str
    locations: list[str]
    types: list[str]


def subscriptions(conn: sqlite3.Connection) -> list[Sub]:
    return [
        Sub(
            endpoint=r["endpoint"],
            keys=json.loads(r["keys_json"]),
            units=r["units"],
            locations=json.loads(r["locations_json"]),
            types=json.loads(r["types_json"]),
        )
        for r in conn.execute("SELECT * FROM push_subs")
    ]


# --- wording -------------------------------------------------------------------

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DANGER = {1: "Low", 2: "Moderate", 3: "Considerable", 4: "High", 5: "Extreme"}


def _day(d: str | None) -> str:
    return _WEEKDAYS[date.fromisoformat(d).weekday()] if d else ""


def _snow(cm: float | None, units: str) -> str:
    if cm is None:
        return "–"
    return f"{cm / 2.54:.0f} in" if units == "imperial" else f"{cm:.0f} cm"


def _speed(kmh: float | None, units: str) -> str:
    if kmh is None:
        return "–"
    return f"{kmh * 0.621371:.0f} mph" if units == "imperial" else f"{kmh:.0f} km/h"


def phrase(f: Flag, units: str) -> str:
    if f.type == "powder_day":
        return f"powder day {_day(f.date)}, {_snow(f.value, units)}"
    if f.type == "storm_incoming":
        return f"storm from {_day(f.date)}: {_snow(f.value, units)} in 48 h"
    if f.type == "wind_hold":
        return f"summit gusts {_speed(f.value, units)} {_day(f.date)}: lift holds likely"
    if f.type == "avalanche_danger":
        level = int(f.value or 0)
        return f"avalanche danger {level} – {DANGER.get(level, '')}"
    return f.type.replace("_", " ")


def message(name: str, location_id: str, flags: list[Flag], units: str) -> dict[str, str]:
    text = "; ".join(phrase(f, units) for f in flags)
    return {
        "title": f"{name}: {text[:1].upper()}{text[1:]}",
        "body": "Tap to see the forecast.",
        "url": f"/location/{location_id}",
        "tag": f"{location_id}-{flags[0].type}",
    }


# --- sending -------------------------------------------------------------------

# (subscription info, JSON payload, private key, claims) -> HTTP status from the push service
Sender = Callable[[Mapping[str, Any], str, str, dict[str, str]], int]


def webpush_sender(info: Mapping[str, Any], data: str, key: str, claims: dict[str, str]) -> int:
    from pywebpush import WebPushException, webpush

    try:
        resp = webpush(
            subscription_info=dict(info),
            data=data,
            vapid_private_key=key,
            vapid_claims=dict(claims),
            ttl=12 * 3600,
            timeout=10,
        )
    except WebPushException as e:
        return e.response.status_code if e.response is not None else 0
    return int(getattr(resp, "status_code", 201))


def send(
    conn: sqlite3.Connection,
    settings: Settings,
    sub: Sub,
    payload: Mapping[str, str],
    sender: Sender = webpush_sender,
) -> bool:
    """Send one notification. Gone subscriptions are removed; repeated failures too."""
    claims = {"sub": contact(settings)}
    info = {"endpoint": sub.endpoint, "keys": sub.keys}
    try:
        status = sender(info, json.dumps(payload), settings.vapid_private_key, claims)
    except Exception as e:  # a push problem must never break a run
        log.warning("push to %s failed: %s", sub.endpoint[:40], e)
        status = 0
    with conn:
        if 200 <= status < 300:
            conn.execute(
                "UPDATE push_subs SET last_ok_at = ?, fail_count = 0 WHERE endpoint = ?",
                (utcnow_iso(), sub.endpoint),
            )
            return True
        if status in (404, 410):  # the browser unsubscribed or the subscription expired
            conn.execute("DELETE FROM push_subs WHERE endpoint = ?", (sub.endpoint,))
            return False
        conn.execute(
            "UPDATE push_subs SET fail_count = fail_count + 1 WHERE endpoint = ?", (sub.endpoint,)
        )
        conn.execute(
            "DELETE FROM push_subs WHERE endpoint = ? AND fail_count >= ?",
            (sub.endpoint, MAX_FAILURES),
        )
    return False


def notify(
    conn: sqlite3.Connection,
    settings: Settings,
    new_flags: Mapping[str, tuple[str, list[Flag]]],
    sender: Sender = webpush_sender,
) -> int:
    """new_flags: location id → (name, flags first raised now). Returns notifications sent."""
    if not enabled(settings) or not new_flags:
        return 0
    sent = 0
    for sub in subscriptions(conn):
        for loc_id, (name, flags) in new_flags.items():
            if sub.locations and loc_id not in sub.locations:
                continue
            mine = [f for f in flags if f.type in sub.types]
            if mine and send(conn, settings, sub, message(name, loc_id, mine, sub.units), sender):
                sent += 1
    return sent


def new_flags_for_run(
    conn: sqlite3.Connection, run_id: int, snaps: Iterable[tuple[str, str, Snapshot]]
) -> dict[str, tuple[str, list[Flag]]]:
    """Flags first raised in this run, skipping a location's very first forecast."""
    out: dict[str, tuple[str, list[Flag]]] = {}
    for loc_id, name, snap in snaps:
        earlier = conn.execute(
            "SELECT 1 FROM snapshots WHERE location_id = ? AND run_id < ? LIMIT 1",
            (loc_id, run_id),
        ).fetchone()
        if earlier is None:
            continue
        flags = [f for f in snap.flags if f.first_run == run_id and f.type in ALERT_TYPES]
        if flags:
            out[loc_id] = (name, flags)
    return out


def avalanche_alerts(
    conn: sqlite3.Connection, levels: Mapping[str, tuple[str, int | None, str | None]]
) -> dict[str, tuple[str, list[Flag]]]:
    """Locations whose current forecast first shows danger 4+ today (once per day each).

    levels: location id → (name, today's highest level, today's date).
    """
    out: dict[str, tuple[str, list[Flag]]] = {}
    with conn:
        for loc_id, (name, level, day) in levels.items():
            if level is None or level < 4 or day is None:
                continue
            seen = conn.execute(
                "SELECT 1 FROM flag_log WHERE location_id = ? AND type = 'avalanche_danger' "
                "AND key = ?",
                (loc_id, day),
            ).fetchone()
            if seen:
                continue
            conn.execute(
                "INSERT INTO flag_log (location_id, type, key, first_run, last_run) "
                "VALUES (?, 'avalanche_danger', ?, 0, 0)",
                (loc_id, day),
            )
            flag = Flag(type="avalanche_danger", severity="warning", date=day, value=float(level))
            out[loc_id] = (name, [flag])
    return out
