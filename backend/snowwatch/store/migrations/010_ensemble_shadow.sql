-- Self-hosted ensembles (docs/OPEN-METEO-PLAN.md, milestone 1b, PR 2).
--
-- ensemble_shadow: with OPEN_METEO_ENSEMBLES=shadow, each time a run fetches a public
-- ensemble it also asks the self-hosted server, and records how the two compare here:
-- members with data, how far ahead each reaches (hours from the run), and the mean and
-- largest difference of the members' 16-day totals (cm). `error` when the server
-- couldn't answer. `local_run` is the run the server held (its meta.json), `public_run`
-- the public data's newest run (the public bucket's meta.json): only comparisons of the
-- same run count towards the differences. The Status page summarises the last 7 days;
-- kept 90.
CREATE TABLE ensemble_shadow (
    run_id         INTEGER NOT NULL,
    location_id    TEXT    NOT NULL,
    system         TEXT    NOT NULL,
    at             TEXT    NOT NULL,
    local_run      TEXT,
    public_run     TEXT,
    members_local  INTEGER,
    members_public INTEGER,
    reach_local_h  REAL,
    reach_public_h REAL,
    mean_diff_cm   REAL,
    max_diff_cm    REAL,
    error          TEXT,
    PRIMARY KEY (run_id, location_id, system)
);
CREATE INDEX ensemble_shadow_at ON ensemble_shadow (at);

-- ensemble_state: with OPEN_METEO_ENSEMBLES=local, where each system's ensembles came
-- from in the last run (`local` 1 = the server, 0 = the public API, and why), and since
-- when, for the Status page and `snowwatch openmeteo status`.
CREATE TABLE ensemble_state (
    system     TEXT PRIMARY KEY,
    local      INTEGER NOT NULL,
    reason     TEXT,
    since      TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
