-- Forecasts anywhere (docs/OPEN-METEO-PLAN.md, milestone 2): ensembles fetched for spots,
-- the points tapped on the map. One answer per system serves every spot in its 0.25°
-- cell at the same 100 m step of elevation (`cell`, e.g. "47.25,-121.5,1800"), for a few
-- hours (`spots.ensemble_cache_h`). That keeps public calls within the spots' daily
-- allowance and bounds the self-hosted server's work. `source`: local (the self-hosted
-- server) or public. Rows older than the cache time go when new ones are written.
CREATE TABLE spot_ensembles (
    cell       TEXT NOT NULL,
    system     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source     TEXT NOT NULL,
    doc_gz     BLOB NOT NULL,
    PRIMARY KEY (cell, system)
);
CREATE INDEX spot_ensembles_at ON spot_ensembles (fetched_at);
