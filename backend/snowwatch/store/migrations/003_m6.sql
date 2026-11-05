-- Milestone M6: webcams per location, per-source status, and Web Push subscriptions.

ALTER TABLE locations ADD COLUMN webcams_json TEXT NOT NULL DEFAULT '[]';

-- The latest outcome per upstream source, for the Status page.
CREATE TABLE source_status (
    source        TEXT PRIMARY KEY,
    last_ok_at    TEXT,
    last_error_at TEXT,
    last_error    TEXT,
    day           TEXT,              -- UTC date the counters below are for
    calls_today   INTEGER NOT NULL DEFAULT 0,
    errors_today  INTEGER NOT NULL DEFAULT 0,
    weight_today  REAL NOT NULL DEFAULT 0
);

-- Browser push subscriptions (W3C Web Push). One row per device.
CREATE TABLE push_subs (
    endpoint       TEXT PRIMARY KEY,
    keys_json      TEXT NOT NULL,     -- {"p256dh": …, "auth": …}
    email          TEXT,
    units          TEXT NOT NULL DEFAULT 'imperial',
    locations_json TEXT NOT NULL DEFAULT '[]',   -- empty = every location
    types_json     TEXT NOT NULL DEFAULT '["powder_day","storm_incoming"]',
    created_at     TEXT NOT NULL,
    last_ok_at     TEXT,
    fail_count     INTEGER NOT NULL DEFAULT 0
);
