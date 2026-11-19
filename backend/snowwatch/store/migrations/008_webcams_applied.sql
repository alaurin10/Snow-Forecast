-- What config/webcams.yaml last said for each location, as applied by the worker or
-- `snowwatch locations webcams` (a digest of the entry's webcams). The worker applies an
-- entry only when it differs from this, so cameras edited on the Manage page stay until
-- the file's entry for that location changes.
CREATE TABLE webcams_applied (
    location_id TEXT PRIMARY KEY,
    digest      TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);
