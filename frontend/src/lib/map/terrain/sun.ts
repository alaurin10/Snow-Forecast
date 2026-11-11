// Where the sun is: azimuth and altitude for a time and place, and the day's sunrise
// and sunset. NOAA's solar calculator formulas (Meeus, simplified), good to a few
// hundredths of a degree for this century, which is far finer than the terrain.

const RAD = Math.PI / 180;
const DEG = 180 / Math.PI;

export interface SunPosition {
	/** Compass degrees, clockwise from north: where the sun is. */
	azimuth: number;
	/** Degrees above the horizon as seen (with refraction); negative when it's down. */
	altitude: number;
}

/** A calendar date at the place being looked at. */
export type Ymd = [year: number, month: number, day: number];

interface Orbit {
	/** Declination, degrees. */
	decl: number;
	/** Equation of time, minutes. */
	eot: number;
}

function orbit(ms: number): Orbit {
	const jd = ms / 86400000 + 2440587.5;
	const t = (jd - 2451545) / 36525;
	const l0 = (((280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360) + 360) % 360;
	const m = 357.52911 + t * (35999.05029 - 0.0001537 * t);
	const e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t);
	const c =
		Math.sin(m * RAD) * (1.914602 - t * (0.004817 + 0.000014 * t)) +
		Math.sin(2 * m * RAD) * (0.019993 - 0.000101 * t) +
		Math.sin(3 * m * RAD) * 0.000289;
	const omega = 125.04 - 1934.136 * t;
	const lambda = l0 + c - 0.00569 - 0.00478 * Math.sin(omega * RAD);
	const eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60;
	const eps = eps0 + 0.00256 * Math.cos(omega * RAD);
	const decl = Math.asin(Math.sin(eps * RAD) * Math.sin(lambda * RAD)) * DEG;
	const y = Math.tan((eps / 2) * RAD) ** 2;
	const eot =
		4 *
		DEG *
		(y * Math.sin(2 * l0 * RAD) -
			2 * e * Math.sin(m * RAD) +
			4 * e * y * Math.sin(m * RAD) * Math.cos(2 * l0 * RAD) -
			0.5 * y * y * Math.sin(4 * l0 * RAD) -
			1.25 * e * e * Math.sin(2 * m * RAD));
	return { decl, eot };
}

/** How much the air lifts the sun's image, in degrees, at a true altitude. */
function refraction(alt: number): number {
	if (alt > 85) return 0;
	const te = Math.tan(alt * RAD);
	let arcsec: number;
	if (alt > 5) arcsec = 58.1 / te - 0.07 / te ** 3 + 0.000086 / te ** 5;
	else if (alt > -0.575)
		arcsec = 1735 + alt * (-518.2 + alt * (103.4 + alt * (-12.79 + alt * 0.711)));
	else arcsec = -20.772 / te;
	return arcsec / 3600;
}

/** The sun's place in the sky at an instant (Unix milliseconds). */
export function sunPosition(ms: number, lat: number, lon: number): SunPosition {
	const { decl, eot } = orbit(ms);
	const minutes = (((ms / 60000) % 1440) + 1440) % 1440;
	const solar = (((minutes + eot + 4 * lon) % 1440) + 1440) % 1440;
	const ha = solar / 4 - 180;
	const cosZen =
		Math.sin(lat * RAD) * Math.sin(decl * RAD) +
		Math.cos(lat * RAD) * Math.cos(decl * RAD) * Math.cos(ha * RAD);
	const zen = Math.acos(Math.min(1, Math.max(-1, cosZen)));
	const altitude = 90 - zen * DEG;
	const denom = Math.cos(lat * RAD) * Math.sin(zen);
	let azimuth: number;
	if (Math.abs(denom) < 1e-9) azimuth = lat > decl ? 180 : 0;
	else {
		const a =
			Math.acos(
				Math.min(
					1,
					Math.max(-1, (Math.sin(lat * RAD) * Math.cos(zen) - Math.sin(decl * RAD)) / denom)
				)
			) * DEG;
		azimuth = ha > 0 ? (a + 180) % 360 : (540 - a) % 360;
	}
	return { azimuth, altitude: altitude + refraction(altitude) };
}

export interface SunDay {
	/** Unix milliseconds; null when the sun doesn't rise or doesn't set that day. */
	sunrise: number | null;
	sunset: number | null;
	/** The sun's highest moment. */
	noon: number;
}

/**
 * Sunrise, solar noon and sunset for a calendar date at a place. The date is the
 * place's own (by its longitude), whatever time zone the device is in.
 */
export function sunDay([y, m, d]: Ymd, lat: number, lon: number): SunDay {
	const midnight = Date.UTC(y, m - 1, d);
	// Local noon in UTC minutes, then once more with the orbit as it is at that moment.
	let noon = midnight + (720 - 4 * lon) * 60000;
	let o = orbit(noon);
	noon = midnight + (720 - 4 * lon - o.eot) * 60000;
	o = orbit(noon);
	// The sun's upper edge on the horizon, with standard refraction.
	const cosH =
		Math.cos(90.833 * RAD) / (Math.cos(lat * RAD) * Math.cos(o.decl * RAD)) -
		Math.tan(lat * RAD) * Math.tan(o.decl * RAD);
	if (cosH > 1 || cosH < -1) return { sunrise: null, sunset: null, noon };
	const half = Math.acos(cosH) * DEG * 4 * 60000;
	return { sunrise: noon - half, sunset: noon + half, noon };
}

/** The calendar date at a longitude for an instant (solar time, to the nearest zone hour). */
export function dateAt(ms: number, lon: number): Ymd {
	const local = new Date(ms + Math.round(lon / 15) * 3600000);
	return [local.getUTCFullYear(), local.getUTCMonth() + 1, local.getUTCDate()];
}

/**
 * Times through a day, evenly spaced from sunrise to sunset, at the middle of each
 * step of about `minutes`. Each stands for `hours` of daylight.
 */
export function daySteps(day: SunDay, minutes: number): { times: number[]; hours: number } {
	if (day.sunrise == null || day.sunset == null) return { times: [], hours: 0 };
	const span = day.sunset - day.sunrise;
	const n = Math.max(1, Math.round(span / (minutes * 60000)));
	const step = span / n;
	const times = Array.from({ length: n }, (_, k) => day.sunrise! + (k + 0.5) * step);
	return { times, hours: step / 3600000 };
}

const COMPASS = [
	'N',
	'NNE',
	'NE',
	'ENE',
	'E',
	'ESE',
	'SE',
	'SSE',
	'S',
	'SSW',
	'SW',
	'WSW',
	'W',
	'WNW',
	'NW',
	'NNW'
];
/** "SSW" for 200°. */
export function compass16(azimuth: number): string {
	return COMPASS[Math.round((((azimuth % 360) + 360) % 360) / 22.5) % 16];
}
