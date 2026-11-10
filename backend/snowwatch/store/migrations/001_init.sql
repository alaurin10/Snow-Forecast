-- Snow Watch schema v1. Units are metric throughout (cm, mm, m, °C).

CREATE TABLE locations (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('resort', 'backcountry')),
    region         TEXT NOT NULL DEFAULT '',
    country        TEXT NOT NULL CHECK (country IN ('US', 'CA')),
    tz             TEXT,
    active         INTEGER NOT NULL DEFAULT 1,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    bands_json     TEXT NOT NULL,
    snotel_triplet TEXT,
    nws_office     TEXT,
    radar_station  TEXT,
    avy_json       TEXT,
    links_json     TEXT NOT NULL DEFAULT '{}',
    catalog_ref    TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    updated_by     TEXT,
    archived_at    TEXT
);

CREATE TABLE jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    location_id  TEXT REFERENCES locations (id),
    status       TEXT NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'running', 'done', 'failed')),
    requested_by TEXT,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT,
    error        TEXT
);
CREATE INDEX jobs_status ON jobs (status, created_at);

CREATE TABLE runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'ok', 'partial', 'failed')),
    errors_json TEXT NOT NULL DEFAULT '[]',
    api_weight  REAL NOT NULL DEFAULT 0
);
CREATE INDEX runs_started ON runs (started_at);

-- The precomputed document the UI renders, one per location per run.
CREATE TABLE snapshots (
    location_id TEXT NOT NULL REFERENCES locations (id),
    run_id      INTEGER NOT NULL REFERENCES runs (id),
    created_at  TEXT NOT NULL,
    doc_gz      BLOB NOT NULL,
    PRIMARY KEY (location_id, run_id)
);

-- Latest ensemble response per system; ensembles are fetched twice a day
-- and reused by the runs in between.
CREATE TABLE ensemble_cache (
    location_id TEXT NOT NULL REFERENCES locations (id),
    system      TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    doc_gz      BLOB NOT NULL,
    PRIMARY KEY (location_id, system)
);

-- Daily forecasts per run for the trend and verification views (mid band).
-- source: cons, each model id, ens_p10 / ens_p50 / ens_p90.
CREATE TABLE forecast_daily (
    location_id TEXT NOT NULL REFERENCES locations (id),
    run_id      INTEGER NOT NULL REFERENCES runs (id),
    issued_at   TEXT NOT NULL,
    target_date TEXT NOT NULL,
    source      TEXT NOT NULL,
    snow_cm     REAL,
    water_mm    REAL,
    PRIMARY KEY (location_id, run_id, target_date, source)
);
CREATE INDEX forecast_daily_target ON forecast_daily (location_id, target_date);

CREATE TABLE obs_daily (
    location_id TEXT NOT NULL REFERENCES locations (id),
    station     TEXT NOT NULL,
    date        TEXT NOT NULL,
    depth_cm    REAL,
    swe_mm      REAL,
    tmin_c      REAL,
    tmax_c      REAL,
    precip_mm   REAL,
    PRIMARY KEY (location_id, station, date)
);

CREATE TABLE obs_hourly (
    location_id TEXT NOT NULL REFERENCES locations (id),
    station     TEXT NOT NULL,
    t           TEXT NOT NULL,
    depth_cm    REAL,
    temp_c      REAL,
    PRIMARY KEY (location_id, station, t)
);

CREATE TABLE alerts (
    location_id TEXT NOT NULL REFERENCES locations (id),
    run_id      INTEGER NOT NULL REFERENCES runs (id),
    event       TEXT,
    headline    TEXT,
    severity    TEXT,
    onset       TEXT,
    ends        TEXT,
    url         TEXT
);
CREATE INDEX alerts_run ON alerts (location_id, run_id);

CREATE TABLE avalanche (
    location_id   TEXT NOT NULL REFERENCES locations (id),
    fetched_at    TEXT NOT NULL,
    issued_at     TEXT,
    expires_at    TEXT,
    center        TEXT,
    zone          TEXT,
    ratings_json  TEXT,
    problems_json TEXT,
    url           TEXT,
    PRIMARY KEY (location_id, fetched_at)
);

CREATE TABLE flag_log (
    location_id TEXT NOT NULL REFERENCES locations (id),
    type        TEXT NOT NULL,
    key         TEXT NOT NULL,
    first_run   INTEGER NOT NULL,
    last_run    INTEGER NOT NULL,
    PRIMARY KEY (location_id, type, key)
);

-- Lookups for the Manage page.
CREATE TABLE catalog_ski_areas (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    country    TEXT,
    region     TEXT,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    min_elev_m REAL,
    max_elev_m REAL,
    activities TEXT,
    status     TEXT,
    website    TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX catalog_name ON catalog_ski_areas (name);

CREATE TABLE snotel_stations (
    triplet    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    state      TEXT,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    elev_m     REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE avy_zones (
    provider      TEXT NOT NULL,
    zone_id       TEXT NOT NULL,
    center_id     TEXT,
    name          TEXT,
    link          TEXT,
    bbox_json     TEXT,
    geometry_json TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (provider, zone_id)
);
