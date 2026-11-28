-- Fresher forecasts (docs/OPEN-METEO-PLAN.md, milestone 4): each model folder's latest
-- run, from its meta.json in the public Open-Meteo data, as the worker last read it
-- (`snowwatch/modelwatch.py`). `available_at` is when the run became available;
-- `changed_at` when this row last saw a newer run. The Status page, each snapshot's
-- `model_runs` and the spot cache's expiry read it.
CREATE TABLE model_runs (
    folder       TEXT PRIMARY KEY,
    init_time    TEXT,
    available_at TEXT,
    changed_at   TEXT NOT NULL,
    checked_at   TEXT NOT NULL
);
