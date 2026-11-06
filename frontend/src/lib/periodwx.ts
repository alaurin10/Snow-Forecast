// Per-period sky and wind direction, read from the band's hourly series, and the
// weather icon to show for a period.
import type { HourlyOut, PeriodOut } from './types.gen';

export type WxIcon =
	| 'clear-day'
	| 'clear-night'
	| 'partly-day'
	| 'partly-night'
	| 'cloud'
	| 'fog'
	| 'rain'
	| 'snow'
	| 'mix'
	| 'thunder';

/** The hourly indexes that fall inside a period. */
function hoursOf(h: HourlyOut, p: PeriodOut): number[] {
	const a = Date.parse(p.start);
	const b = a + p.hours * 3600e3;
	const out: number[] = [];
	h.t.forEach((t, i) => {
		const x = Date.parse(t);
		if (x >= a && x < b) out.push(i);
	});
	return out;
}

/** The most significant weather code and the wind direction at mid-period. */
export function periodWeather(
	h: HourlyOut,
	p: PeriodOut
): { wcode: number | null; wdir: number | null } {
	const idx = hoursOf(h, p);
	if (!idx.length) return { wcode: null, wdir: null };
	const codes = idx
		.map((i) => h.wcode[i])
		.filter((v): v is number => v !== null && v !== undefined);
	return {
		wcode: codes.length ? Math.max(...codes) : null,
		wdir: h.wdir[idx[Math.floor(idx.length / 2)]] ?? null
	};
}

/** Precipitation type decides the icon when it snows or rains; otherwise the sky does. */
export function wxIcon(p: PeriodOut, wcode: number | null): WxIcon {
	const night = p.kind === 'night';
	if (wcode !== null && wcode >= 95) return 'thunder';
	const wet = (p.snow_cm ?? 0) > 0.2 || (p.rain_mm ?? 0) > 0.2;
	if (wet && p.ptype === 'snow') return 'snow';
	if (wet && p.ptype === 'mix') return 'mix';
	if (wet && p.ptype === 'rain') return 'rain';
	if (wcode === null) return 'cloud';
	if (wcode === 45 || wcode === 48) return 'fog';
	if (wcode >= 71 && wcode <= 86 && wcode !== 80 && wcode !== 81 && wcode !== 82) return 'snow';
	if (wcode >= 51) return 'rain';
	if (wcode === 3) return 'cloud';
	if (wcode === 2) return night ? 'partly-night' : 'partly-day';
	return night ? 'clear-night' : 'clear-day';
}
