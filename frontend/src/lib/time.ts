// Snapshot times are local ISO strings with their UTC offset
// ("2026-11-04T14:00-07:00"). The wall-clock parts are read straight from the
// string, so labels are always in the location's time, never the browser's.

export const hourOf = (iso: string): number => Number(iso.slice(11, 13));
export const dateOf = (iso: string): string => iso.slice(0, 10);

const WEEKDAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "Thu" for a YYYY-MM-DD date (a calendar date has no timezone). */
export function weekday(date: string): string {
	const [y, m, d] = date.split('-').map(Number);
	return WEEKDAY[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}

export function monthDay(date: string): string {
	const [, m, d] = date.split('-').map(Number);
	return `${MONTH[m - 1]} ${d}`;
}

/** "2 PM", "Noon", "Midnight" from a local ISO time. */
export function hourLabel(iso: string): string {
	const h = hourOf(iso);
	if (h === 0) return 'Midnight';
	if (h === 12) return 'Noon';
	return h < 12 ? `${h} AM` : `${h - 12} PM`;
}

/** "Thu 2 PM" */
export function dayHour(iso: string): string {
	return `${weekday(dateOf(iso))} ${hourLabel(iso)}`;
}

/** Minutes between two ISO instants. */
export const minutesBetween = (a: string, b: string): number =>
	(Date.parse(b) - Date.parse(a)) / 60000;
