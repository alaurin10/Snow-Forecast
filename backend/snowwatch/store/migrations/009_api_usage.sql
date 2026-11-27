-- Open-Meteo requests per UTC day (the public API's daily limit resets at 00:00 UTC) and
-- host: the public hosts with their weight against that limit, and the self-hosted
-- server as `local` (free; its seconds give the Status page's latency). `fallbacks`
-- counts a public host's requests that retried a failed self-hosted one. The worker adds
-- a run's requests when it finishes; everything that spends public calls reads today's
-- total first (docs/OPEN-METEO-PLAN.md, milestone 1).
CREATE TABLE api_usage (
    day       TEXT    NOT NULL,
    host      TEXT    NOT NULL,
    weight    REAL    NOT NULL DEFAULT 0,
    requests  INTEGER NOT NULL DEFAULT 0,
    fallbacks INTEGER NOT NULL DEFAULT 0,
    seconds   REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (day, host)
);
