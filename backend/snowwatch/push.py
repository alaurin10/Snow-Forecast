"""Phone and desktop alerts through the W3C Web Push API.

The browser subscribes with our VAPID public key and hands us an endpoint at its
push service (Google, Apple or Mozilla). We encrypt a small JSON payload for
that subscription and POST it there; the service worker shows it. Push is off
until VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are set (`snowwatch push keys`).

Each forecast run sends a device at most one notification: a digest of every
location it follows that has something new. An event (a powder day, a storm, a
wind hold) alerts once, when it first shows up within LEAD_DAYS, and again only if
it grows a lot; `push_log` remembers what was sent so a flag that flickers or a
storm whose start moves by a day stays quiet (see `alertable_flags`).
"""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from snowwatch.doc import Flag, Snapshot
from snowwatch.settings import Settings
from snowwatch.store.db import utcnow_iso

log = logging.getLogger("snowwatch.push")

ALERT_TYPES = ("powder_day", "storm_incoming", "wind_hold", "avalanche_danger")
DEFAULT_TYPES = ["powder_day", "storm_incoming"]
MAX_FAILURES = 5

LEAD_DAYS = 5  # powder days and storms alert once they're this close (days ahead)
REALERT_AFTER_H = 24  # an event gone this long counts as new when it comes back
ESCALATE_RATIO = 1.5  # an event already sent alerts again at 1.5× the amount…
ESCALATE_MIN_CM = 10  # …and at least this much more
STORM_DAYS = 2  # a storm covers its start day and the two after (48 h)

# The browsers' own push services. The server POSTs to a subscription's endpoint,
# so only these hosts are accepted: anything else would let a visitor make the
# server send requests wherever they like.
PUSH_HOSTS = frozenset(
    {
        "fcm.googleapis.com",  # Chrome, Edge, Android
        "android.googleapis.com",
        "updates.push.services.mozilla.com",  # Firefox
        "web.push.apple.com",  # Safari, iOS
    }
)
PUSH_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com", ".push.services.mozilla.com")


def is_push_service(endpoint: str) -> bool:
    try:
        u = urlsplit(endpoint)
        port = u.port
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return (
        u.scheme == "https"
        and port is None
        and not u.username
        and (host in PUSH_HOSTS or host.endswith(PUSH_HOST_SUFFIXES))
    )


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class PushSubscription(BaseModel):
    """What `PushManager.subscribe()` returns (its toJSON())."""

    endpoint: str = Field(max_length=1000)
    keys: SubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def _push_service(cls, v: str) -> str:
        if not is_push_service(v):
            raise ValueError("not a browser push service address")
        return v


class Endpoint(BaseModel):
    """Identifies a subscription without its keys (unsubscribe, test, prefs)."""

    endpoint: str = Field(max_length=1000)


Units = Literal["imperial", "metric"]


class AlertPrefs(BaseModel):
    locations: list[Annotated[str, Field(max_length=40)]] = Field(default=[], max_length=100)
    types: list[Annotated[str, Field(max_length=40)]] = Field(
        default=DEFAULT_TYPES, max_length=len(ALERT_TYPES)
    )
    units: Units = "imperial"


class SubscribeIn(AlertPrefs):
    subscription: PushSubscription


class SubscriptionLimitError(Exception):
    """The server already holds as many subscriptions as it allows."""


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
    for candidate in [settings.contact_email, settings.nws_contact]:
        if candidate and "@" in candidate and " " not in candidate.strip():
            return f"mailto:{candidate.strip()}"
    return "mailto:snowwatch@example.com"


def enabled(settings: Settings) -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


# --- subscriptions -------------------------------------------------------------


def subscribe(conn: sqlite3.Connection, body: SubscribeIn, *, max_subs: int = 500) -> None:
    types = [t for t in body.types if t in ALERT_TYPES] or DEFAULT_TYPES
    with conn:
        known = conn.execute(
            "SELECT 1 FROM push_subs WHERE endpoint = ?", (body.subscription.endpoint,)
        ).fetchone()
        if not known:
            count = conn.execute("SELECT COUNT(*) FROM push_subs").fetchone()[0]
            if count >= max_subs:
                raise SubscriptionLimitError
        conn.execute(
            "INSERT INTO push_subs (endpoint, keys_json, units, locations_json, "
            "types_json, created_at, fail_count) VALUES (?, ?, ?, ?, ?, ?, 0) "
            "ON CONFLICT (endpoint) DO UPDATE SET keys_json = excluded.keys_json, "
            "units = excluded.units, "
            "locations_json = excluded.locations_json, types_json = excluded.types_json, "
            "fail_count = 0",
            (
                body.subscription.endpoint,
                body.subscription.keys.model_dump_json(),
                body.units,
                json.dumps(body.locations),
                json.dumps(types),
                utcnow_iso(),
            ),
        )


def prefs(conn: sqlite3.Connection, endpoint: str) -> AlertPrefs | None:
    """What a subscription asked for, so the Alerts card can show it."""
    row = conn.execute(
        "SELECT units, locations_json, types_json FROM push_subs WHERE endpoint = ?", (endpoint,)
    ).fetchone()
    if row is None:
        return None
    return AlertPrefs(
        locations=json.loads(row["locations_json"]),
        types=json.loads(row["types_json"]),
        units=row["units"],
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
SNOW_TYPES = ("powder_day", "storm_incoming")
SEVERITY = {"warning": 0, "notice": 1, "info": 2}
DIGEST_LINES = 4  # about what a collapsed notification shows
DIGEST_TAG = "snowwatch-digest"  # each digest replaces the last one


@dataclass
class Alert:
    flag: Flag
    was: float | None = None  # an escalation: the amount people were told before


# location id -> (name, alerts)
Found = dict[str, tuple[str, list[Alert]]]


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


def _cap(text: str) -> str:
    return f"{text[:1].upper()}{text[1:]}"


def phrase(f: Flag, units: str, was: float | None = None) -> str:
    now = "now " if was is not None else ""
    if f.type == "powder_day":
        return f"powder day {_day(f.date)}, {now}{_snow(f.value, units)}"
    if f.type == "storm_incoming":
        if was is not None:
            return f"storm from {_day(f.date)}, now {_snow(f.value, units)} in 48 h"
        return f"storm from {_day(f.date)}: {_snow(f.value, units)} in 48 h"
    if f.type == "wind_hold":
        return f"summit gusts {_speed(f.value, units)} {_day(f.date)}: lift holds likely"
    if f.type == "avalanche_danger":
        level = int(f.value or 0)
        return f"avalanche danger {level} – {DANGER.get(level, '')}"
    return f.type.replace("_", " ")


def _headline(f: Flag, units: str) -> str:
    """The top alert, short, for a digest's title."""
    if f.type == "powder_day":
        return f"{_snow(f.value, units)} {_day(f.date)}"
    if f.type == "storm_incoming":
        return f"{_snow(f.value, units)} from {_day(f.date)}"
    if f.type == "wind_hold":
        return f"gusts {_speed(f.value, units)} {_day(f.date)}"
    if f.type == "avalanche_danger":
        return f"avalanche danger {DANGER.get(int(f.value or 0), '')}"
    return f.type.replace("_", " ")


def _rank(a: Alert) -> tuple[int, int, float]:
    """Warnings first, snow before wind and avalanche, then the most snow."""
    f = a.flag
    snow = 0 if f.type in SNOW_TYPES else 1
    return SEVERITY.get(f.severity, 3), snow, -(f.value or 0) if snow == 0 else 0


def _in_storm(powder_day: str | None, storm_day: str | None) -> bool:
    """A powder day within a storm's 48 h (its start day and the two after)."""
    if not powder_day or not storm_day:
        return False
    days = (date.fromisoformat(powder_day) - date.fromisoformat(storm_day)).days
    return 0 <= days <= STORM_DAYS


def phrases(alerts: list[Alert], units: str) -> list[str]:
    """A location's alerts, best first, with powder days inside a storm folded into it."""
    ordered = sorted(alerts, key=_rank)
    inside: dict[int, list[Alert]] = {}  # storm -> its powder days
    for s in ordered:
        if s.flag.type == "storm_incoming":
            inside[id(s)] = [
                p
                for p in ordered
                if p.flag.type == "powder_day" and _in_storm(p.flag.date, s.flag.date)
            ]
    folded = {id(p) for days in inside.values() for p in days}
    out: list[str] = []
    for a in ordered:
        if id(a) in folded:
            continue  # shown with its storm
        text = phrase(a.flag, units, a.was)
        if days := inside.get(id(a)):
            best = max(days, key=lambda p: p.flag.value or 0)
            text += f" (powder {_day(best.flag.date)})"
        out.append(text)
    return out


def _kind(alerts: list[Alert]) -> str:
    types = {a.flag.type for a in alerts}
    if types == {"powder_day"}:
        return "Powder"
    if types == {"storm_incoming"}:
        return "Storms"
    if types <= set(SNOW_TYPES):
        return "Snow"
    return "Alerts"


def digest(items: list[tuple[str, str, list[Alert]]], units: str) -> dict[str, str]:
    """One notification for a run: items are (location id, name, alerts)."""
    items = sorted(items, key=lambda it: min(_rank(a) for a in it[2]))
    if len(items) == 1:
        loc_id, name, alerts = items[0]
        texts = phrases(alerts, units)
        rest = "; ".join(texts[1:])
        return {
            "title": f"{name}: {_cap(texts[0])}",
            "body": _cap(rest) if rest else "Tap to see the forecast.",
            "url": f"/location/{loc_id}",
            "tag": DIGEST_TAG,
        }
    _, top_name, top_alerts = items[0]
    top = min(top_alerts, key=_rank).flag
    every = [a for _, _, alerts in items for a in alerts]
    shown = items if len(items) <= DIGEST_LINES else items[: DIGEST_LINES - 1]
    lines = [f"{name}: {'; '.join(phrases(alerts, units)[:2])}" for _, name, alerts in shown]
    if len(shown) < len(items):
        lines.append(f"+{len(items) - len(shown)} more")
    return {
        "title": f"{_kind(every)} at {len(items)} spots: {top_name} {_headline(top, units)}",
        "body": "\n".join(lines),
        "url": "/",
        "tag": DIGEST_TAG,
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
    found: Mapping[str, tuple[str, list[Alert]]],
    sender: Sender = webpush_sender,
) -> int:
    """At most one notification per subscription, covering every location it follows.

    found: location id -> (name, alerts). Returns notifications sent.
    """
    if not enabled(settings) or not found:
        return 0
    sent = 0
    for sub in subscriptions(conn):
        items = []
        for loc_id, (name, alerts) in found.items():
            if sub.locations and loc_id not in sub.locations:
                continue
            mine = [a for a in alerts if a.flag.type in sub.types]
            if mine:
                items.append((loc_id, name, mine))
        if items and send(conn, settings, sub, digest(items, sub.units), sender):
            sent += 1
    return sent


# --- what's worth an alert -------------------------------------------------------


@dataclass
class _Logged:
    type: str
    date: str
    value: float | None
    severity: str | None
    alerted_at: str | None
    last_seen_at: str


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _match(rows: list[_Logged], ftype: str, day: str) -> _Logged | None:
    """The logged event a flag continues: same day, or for a storm within a day."""
    if ftype == "storm_incoming":
        near = [r for r in rows if r.type == ftype and abs(_days_between(r.date, day)) <= 1]
        return min(near, key=lambda r: abs(_days_between(r.date, day)), default=None)
    return next((r for r in rows if r.type == ftype and r.date == day), None)


def _escalated(row: _Logged, f: Flag) -> bool:
    if SEVERITY.get(f.severity, 3) < SEVERITY.get(row.severity or "", 3):
        return True
    if f.type not in SNOW_TYPES or row.value is None or f.value is None:
        return False
    return f.value >= ESCALATE_RATIO * row.value and f.value - row.value >= ESCALATE_MIN_CM


def alertable_flags(
    conn: sqlite3.Connection,
    run_id: int,
    snaps: Iterable[tuple[str, str, Snapshot]],
    now: datetime | None = None,
) -> Found:
    """Flags worth a notification after this run, and the push_log kept up to date.

    An event alerts once: when it first shows up within LEAD_DAYS (a storm or powder
    day), and again only if it grows a lot (or becomes a warning). One that drops out
    and comes back within REALERT_AFTER_H hours is the same event; a storm whose start
    moves by a day too, and so is a powder day inside a storm already sent. A
    location's very first forecast alerts nothing (it would raise everything at once).
    """
    now = now or datetime.now(UTC)
    stamp = now.isoformat(timespec="seconds")
    fresh = (now - timedelta(hours=REALERT_AFTER_H)).isoformat(timespec="seconds")
    out: Found = {}
    for loc_id, name, snap in snaps:
        earlier = conn.execute(
            "SELECT 1 FROM snapshots WHERE location_id = ? AND run_id < ? LIMIT 1",
            (loc_id, run_id),
        ).fetchone()
        quiet = earlier is None
        rows = [
            _Logged(
                r["type"], r["date"], r["value"], r["severity"], r["alerted_at"], r["last_seen_at"]
            )
            for r in conn.execute(
                "SELECT type, date, value, severity, alerted_at, last_seen_at FROM push_log "
                "WHERE location_id = ? AND last_seen_at >= ?",
                (loc_id, fresh),
            )
        ]
        sent_storms = [r for r in rows if r.type == "storm_incoming" and r.alerted_at]
        first_day = snap.days[0].date if snap.days else None
        alerts: list[Alert] = []
        writes: list[tuple[Flag, _Logged | None, bool]] = []  # flag, row it continues, told
        for f in snap.flags:
            if f.type not in ALERT_TYPES or f.type == "avalanche_danger" or not f.date:
                continue
            near = (
                f.type not in SNOW_TYPES
                or first_day is None
                or _days_between(first_day, f.date) <= LEAD_DAYS
            )
            row = _match(rows, f.type, f.date)
            told = row is not None and row.alerted_at is not None
            if quiet:
                writes.append((f, row, True))
            elif not told:
                in_storm = f.type == "powder_day" and any(
                    _in_storm(f.date, s.date) for s in sent_storms
                )
                if near and not in_storm:
                    alerts.append(Alert(f))
                writes.append((f, row, near))
            elif row is not None and row.value is None:
                writes.append((f, row, True))  # logged before amounts were: take it as told
            elif row is not None and near and _escalated(row, f):
                alerts.append(Alert(f, was=row.value))
                writes.append((f, row, True))
            else:
                writes.append((f, row, False))
        with conn:
            for f, row, told_now in writes:
                assert f.date is not None
                if row is not None and row.date != f.date:  # a storm that moved
                    conn.execute(
                        "DELETE FROM push_log WHERE location_id = ? AND type = ? AND date = ?",
                        (loc_id, f.type, f.date),
                    )
                    conn.execute(
                        "UPDATE push_log SET date = ? WHERE location_id = ? AND type = ? "
                        "AND date = ?",
                        (f.date, loc_id, f.type, row.date),
                    )
                if told_now:
                    conn.execute(
                        "INSERT INTO push_log (location_id, type, date, value, severity, "
                        "alerted_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (location_id, type, date) DO UPDATE SET "
                        "value = excluded.value, severity = excluded.severity, "
                        "alerted_at = excluded.alerted_at, last_seen_at = excluded.last_seen_at",
                        (loc_id, f.type, f.date, f.value, f.severity, stamp, stamp),
                    )
                else:
                    conn.execute(
                        "INSERT INTO push_log (location_id, type, date, value, severity, "
                        "alerted_at, last_seen_at) VALUES (?, ?, ?, ?, ?, NULL, ?) "
                        "ON CONFLICT (location_id, type, date) DO UPDATE SET "
                        "last_seen_at = excluded.last_seen_at, "
                        "value = CASE WHEN push_log.alerted_at IS NULL "
                        "THEN excluded.value ELSE push_log.value END, "
                        "severity = CASE WHEN push_log.alerted_at IS NULL "
                        "THEN excluded.severity ELSE push_log.severity END",
                        (loc_id, f.type, f.date, f.value, f.severity, stamp),
                    )
        if alerts:
            out[loc_id] = (name, alerts)
    return out


def avalanche_alerts(
    conn: sqlite3.Connection, levels: Mapping[str, tuple[str, int | None, str | None]]
) -> Found:
    """Locations whose current forecast first shows danger 4+ today (once per day each).

    levels: location id → (name, today's highest level, today's date).
    """
    out: Found = {}
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
            out[loc_id] = (name, [Alert(flag)])
    return out
