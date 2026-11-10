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

/** "5 min ago", "3 h ago", "2 days ago" for an instant (never "in the future"). */
export function ago(iso: string | null | undefined, now: number = Date.now()): string {
	if (!iso) return 'never';
	const m = Math.max(0, Math.round((now - Date.parse(iso)) / 60000));
	if (m < 60) return `${m} min ago`;
	const h = Math.round(m / 60);
	return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`;
}

/** "Nov 4, 2:00 PM PST" for an instant, in `tz` (the location's) or the browser's zone.
 * The zone is named, so times from different places never look alike. */
export function instant(iso: string | null | undefined, tz?: string): string {
	if (!iso) return '–';
	return new Date(iso).toLocaleString('en-US', {
		timeZone: tz,
		month: 'short',
		day: 'numeric',
		hour: 'numeric',
		minute: '2-digit',
		timeZoneName: 'short'
	});
}
