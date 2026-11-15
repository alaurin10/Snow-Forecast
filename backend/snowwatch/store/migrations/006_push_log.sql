-- What push alerts last told people about, per location and event, so a flag that
-- flickers, a storm whose start moves by a day, or a small change to the amount
-- doesn't alert again. `value` and `severity` are what was last sent (or quietly
-- taken as known); `alerted_at` is NULL while an event is seen but too far ahead
-- to alert.
CREATE TABLE push_log (
    location_id  TEXT NOT NULL REFERENCES locations (id),
    type         TEXT NOT NULL,
    date         TEXT NOT NULL,
    value        REAL,
    severity     TEXT,
    alerted_at   TEXT,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (location_id, type, date)
);

-- Flags already raised were alerted the old way: count them as told, so the first
-- run after this change doesn't send them all again.
INSERT INTO push_log (location_id, type, date, value, severity, alerted_at, last_seen_at)
SELECT f.location_id, f.type, f.key, NULL, NULL,
       strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'),
       COALESCE(
           (SELECT r.started_at FROM runs r WHERE r.id = f.last_run),
           strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
       )
FROM flag_log f
WHERE f.type IN ('powder_day', 'storm_incoming', 'wind_hold') AND f.key != '';
