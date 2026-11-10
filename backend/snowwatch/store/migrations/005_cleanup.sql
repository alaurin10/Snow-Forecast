-- Tables nothing reads: NWS alerts live in each snapshot, and hourly observations
-- were never stored.
DROP TABLE IF EXISTS alerts;
DROP TABLE IF EXISTS obs_hourly;

-- Retention deletes runs that no forecast row refers to; the trend reads by run.
CREATE INDEX IF NOT EXISTS forecast_daily_run ON forecast_daily (run_id);
