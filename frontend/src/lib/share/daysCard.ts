// Share image of Day by day: one row per day with day and night snow as a split bar,
// the high and low, wind and the lowest snow level.
import type { BandOut, PeriodOut } from '../types.gen';
import { HEAVY_CM, precipKind, type PrecipKind } from '../daybars';
import { converters, elevation, type UnitSystem } from '../units';
import { monthDay, weekday } from '../time';
import {
	ellipsize,
	fillRound,
	font,
	frame,
	legend,
	madeAt,
	statRow,
	text,
	type Ctx,
	type Palette,
	type Shape
} from './canvas';

export interface DaysShare {
	name: string;
	region: string;
	band: BandOut;
	units: UnitSystem;
	days: number;
	generatedAt: string;
}

export interface DayRow {
	date: string;
	day: PeriodOut | null;
	night: PeriodOut | null;
	/** Snow for the day and the night after it (cm). */
	total: number;
	hi: number | null;
	lo: number | null;
	wind: number | null;
	gust: number | null;
	level: number | null;
	rainMm: number;
}

/** Periods grouped into calendar days (day, then its night), the first `days` of them. */
export function dayRows(periods: PeriodOut[], days: number): DayRow[] {
	const byDate = new Map<string, { day: PeriodOut | null; night: PeriodOut | null }>();
	for (const p of periods) {
		const slot = byDate.get(p.date) ?? { day: null, night: null };
		if (p.kind === 'night') slot.night = p;
		else slot.day = p;
		byDate.set(p.date, slot);
	}
	const nums = (xs: (number | null | undefined)[]) =>
		xs.filter((v): v is number => v !== null && v !== undefined);
	return [...byDate.entries()].slice(0, days).map(([date, { day, night }]) => {
		const both = [day, night].filter((x): x is PeriodOut => x !== null);
		const max = (xs: number[]) => (xs.length ? Math.max(...xs) : null);
		const min = (xs: number[]) => (xs.length ? Math.min(...xs) : null);
		return {
			date,
			day,
			night,
			total: both.reduce((a, p) => a + (p.snow_cm ?? 0), 0),
			hi: max(nums(both.map((p) => p.tmax_c))),
			lo: min(nums(both.map((p) => p.tmin_c))),
			wind: max(nums(both.map((p) => p.wind_max_kmh))),
			gust: max(nums(both.map((p) => p.gust_max_kmh))),
			level: min(nums(both.map((p) => p.snow_level_min_m))),
			rainMm: both.reduce((a, p) => a + (p.rain_mm ?? 0), 0)
		};
	});
}

export function drawDaysCard(ctx: Ctx, shape: Shape, d: DaysShare, p: Palette): void {
	const c = converters(d.units);
	const rows = dayRows(d.band.periods, d.days);
	const r = frame(
		ctx,
		shape,
		{
			eyebrow: `Day by day · next ${rows.length} days`,
			title: d.name,
			subtitle: `${d.region} · ${d.band.label} ${elevation(d.band.elev_m, d.units)}`,
			note: `Forecast from ${madeAt(d.generatedAt)}`
		},
		p
	);
	if (!rows.length) {
		font(ctx, 28, 400);
		text(ctx, 'No forecast yet.', r.x, r.y + 40, p.text2);
		return;
	}
	const snowTxt = (cm: number) => `${(c.snow(cm) ?? 0).toFixed(c.snowDigits)} ${c.snowUnit}`;
	const total = rows.reduce((a, x) => a + x.total, 0);
	const best = rows.reduce((a, x) => (x.total > a.total ? x : a), rows[0]);
	const level = rows.map((x) => x.level).filter((v): v is number => v !== null);
	const used = statRow(
		ctx,
		r,
		[
			{
				label: 'Total snow',
				value: snowTxt(total),
				sub: `next ${rows.length} days`,
				color: p.snow
			},
			{
				label: 'Snowiest day',
				value: best.total > 0 ? snowTxt(best.total) : '–',
				sub: best.total > 0 ? `${weekday(best.date)} ${monthDay(best.date)}` : 'no snow'
			},
			{
				label: 'Lowest snow level',
				value: level.length ? elevation(Math.min(...level), d.units) : '–',
				sub: 'for the period'
			}
		],
		p
	);
	const legendH = legend(
		ctx,
		r,
		[
			{ label: 'Day', color: p.snow },
			{ label: 'Night (lighter)', color: p.snow, alpha: 0.55 },
			{ label: `Snow on a ${c.snowUnit === 'in' ? '6+ in' : '15+ cm'} day`, color: p.heavy },
			{ label: 'Mixed', color: p.mix },
			{ label: 'Rain', color: p.rain }
		],
		p
	);

	// Columns, right edges measured from the right: snow level, wind, high / low, the
	// snow amount; the bar fills what is left after the day name.
	const top = r.y + used + 16;
	const bottom = r.y + r.h - legendH - 14;
	const wide = shape === 'landscape';
	const levelR = r.x + r.w;
	const windR = levelR - (wide ? 200 : 140);
	const tempR = windR - (wide ? 170 : 150);
	const amtR = tempR - (wide ? 210 : 150);
	const barX = r.x + (wide ? 150 : 128);
	const barEnd = amtR - 92;
	const headH = 34;
	font(ctx, 20, 600);
	text(ctx, `Snow (${c.snowUnit})`, barX, top + 22, p.text3);
	text(ctx, 'Hi / Lo', tempR, top + 22, p.text3, 'right');
	text(ctx, `Wind (${c.speedUnit})`, windR, top + 22, p.text3, 'right');
	text(ctx, 'Snow level', levelR, top + 22, p.text3, 'right');
	ctx.fillStyle = p.border;
	ctx.fillRect(r.x, top + headH, r.w, 1.5);

	const rowH = Math.min(118, (bottom - top - headH - 4) / rows.length);
	const max = Math.max(HEAVY_CM / 2, ...rows.map((x) => x.total));
	const color: Record<PrecipKind, string> = {
		snow: p.snow,
		heavy: p.heavy,
		mix: p.mix,
		rain: p.rain,
		none: p.snow
	};
	const big = rowH >= 70;
	rows.forEach((row, k) => {
		const y0 = top + headH + 4 + k * rowH;
		const cy = y0 + rowH / 2;
		if (k % 2 === 1) {
			ctx.globalAlpha = p.dark ? 0.5 : 0.6;
			fillRound(ctx, r.x - 12, y0 + 2, r.w + 24, rowH - 4, 12, p.surface2);
			ctx.globalAlpha = 1;
		}
		// Day.
		font(ctx, big ? 30 : 25, 600);
		const label = k === 0 && row.day?.label === 'Today' ? 'Today' : weekday(row.date);
		text(ctx, label, r.x, cy - (big ? 4 : 2), p.text);
		font(ctx, big ? 21 : 18, 400);
		text(ctx, monthDay(row.date), r.x, cy + (big ? 24 : 19), p.text3);

		// Split bar: day then night, each in its own type colour (night lighter).
		const heavy = row.total >= HEAVY_CM;
		const trackW = barEnd - barX;
		const bh = big ? 16 : 12;
		fillRound(ctx, barX, cy - bh / 2, trackW, bh, bh / 2, p.surface2);
		let x = barX;
		for (const [half, alpha] of [
			[row.day, 1],
			[row.night, 0.55]
		] as const) {
			const cm = half?.snow_cm ?? 0;
			if (!half || cm <= 0) continue;
			const w = Math.min(Math.max(bh, (cm / max) * trackW), barX + trackW - x);
			if (w <= 0) continue;
			ctx.globalAlpha = alpha;
			fillRound(ctx, x, cy - bh / 2, w, bh, bh / 2, color[precipKind(half.ptype, cm, heavy)]);
			ctx.globalAlpha = 1;
			x += w;
		}

		// Snow amount, with any rain (as water) under it.
		const rainy = row.rainMm >= (d.units === 'imperial' ? 0.25 : 0.2);
		font(ctx, big ? 34 : 27, 600, true);
		const amt = (c.snow(row.total) ?? 0).toFixed(c.snowDigits);
		const amtY = cy + (rainy && big ? 4 : big ? 12 : 9);
		text(ctx, amt, amtR, amtY, row.total > 0.05 ? p.text : p.text3, 'right');
		if (rainy && big) {
			font(ctx, 18, 600);
			const rain = `+${(c.water(row.rainMm) ?? 0).toFixed(c.waterDigits)} ${c.waterUnit} rain`;
			text(ctx, ellipsize(ctx, rain, amtR - barEnd + 40), amtR, cy + 32, p.rain, 'right');
		}

		// High / low.
		const t = (v: number | null) => (v === null ? '–' : `${Math.round(c.temp(v) ?? 0)}°`);
		font(ctx, big ? 24 : 20, 500, true);
		const loW = text(ctx, t(row.lo), tempR, cy + 9, p.text3, 'right');
		font(ctx, big ? 28 : 23, 600, true);
		text(ctx, `${t(row.hi)} /`, tempR - loW - 8, cy + 9, p.text, 'right');

		// Wind, with gusts under it.
		font(ctx, big ? 26 : 22, 600, true);
		const w = row.wind === null ? '–' : String(Math.round(c.speed(row.wind) ?? 0));
		text(ctx, w, windR, cy + (big ? 2 : 8), p.text, 'right');
		if (big && row.gust !== null) {
			font(ctx, 19, 400);
			text(ctx, `gusts ${Math.round(c.speed(row.gust) ?? 0)}`, windR, cy + 28, p.text3, 'right');
		}

		// Lowest snow level.
		font(ctx, big ? 24 : 21, 500, true);
		const lvl = row.level === null ? '–' : elevation(row.level, d.units);
		text(ctx, lvl, levelR, cy + 9, p.text2, 'right');
	});
}
