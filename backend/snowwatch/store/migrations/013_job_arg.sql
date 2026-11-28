-- Adding several ski areas from the catalog at once (docs/OPEN-METEO-PLAN.md, milestone
-- 4): each is a queued job of kind `catalog` whose `arg` is the catalog id (the location
-- doesn't exist until the worker has resolved it, so `location_id` can't hold it).
ALTER TABLE jobs ADD COLUMN arg TEXT;
