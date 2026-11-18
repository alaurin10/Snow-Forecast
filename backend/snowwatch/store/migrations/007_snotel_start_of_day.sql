-- SNOTEL's daily values are dated by the day they close (the midnight reading that
-- ends it); Snow Watch's days hold the reading at the start of the day. Rows stored
-- before the parser learned this move to the next date, so the scorecard's new snow
-- lands on the day it fell. BC stations (`…:BC:ASWS`) were already start-of-day.
CREATE TEMP TABLE obs_daily_shift AS
SELECT * FROM obs_daily WHERE station LIKE '%:SNTL';

DELETE FROM obs_daily WHERE station LIKE '%:SNTL';

INSERT INTO obs_daily (location_id, station, date, depth_cm, swe_mm, tmin_c, tmax_c, precip_mm)
SELECT location_id, station, date(date, '+1 day'), depth_cm, swe_mm, tmin_c, tmax_c, precip_mm
FROM obs_daily_shift;

DROP TABLE obs_daily_shift;
