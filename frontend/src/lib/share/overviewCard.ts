// Share image of the Overview: the picked locations' next 7 days of snow as a table.
// The day names sit once in a header; each row is the name, a week of bars on one shared
// scale so the rows compare, and the total. Rows and type scale to how many there are.
import type { OverviewRow } from '../types.gen';
import { dailyTotals, HEAVY_CM, type PrecipKind } from '../daybars';
import { converters, type UnitSystem } from '../units';
import { weekday } from '../time';
import {
	ellipsize,
	fillRound,
	fitSize,
	font,
	frame,
	legend,
	madeAt,
	text,
	type Ctx,
	type Palette,
	type Shape
} from './canvas';

/** The most locations one image holds and stays readable on a phone. */
export const OVERVIEW_MAX = 12;
/** Landscape images split into two columns past this many rows. */
const LANDSCAPE_ONE_COLUMN = 6;

export interface OverviewShare {
	/** The locations to draw, in order; only the first OVERVIEW_MAX with a forecast are drawn. */
	rows: OverviewRow[];
	units: UnitSystem;
	days: number;
	generatedAt: string;
}

/** A location's snow over the next `days` days (cm), the same sum its bars add up to. */
export function weekTotal(row: OverviewRow, days: number): number {
	return dailyTotals(row.periods ?? [], days).reduce((a, t) => a + t.cm, 0);
}

/**
 * The locations a fresh share starts with: every one with a forecast when they fit,
 * else the snowiest `max` of them.
 */
export function defaultShareIds(rows: OverviewRow[], days: number, max = OVERVIEW_MAX): string[] {
	const ready = rows.filter((r) => r.run_id != null);
	if (ready.length <= max) return ready.map((r) => r.id);
	return ready
		.map((r, i) => ({ id: r.id, i, total: weekTotal(r, days) }))
		.sort((a, b) => b.total - a.total || a.i - b.i)
		.slice(0, max)
		.map((x) => x.id);
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function drawOverviewCard(ctx: Ctx, shape: Shape, d: OverviewShare, p: Palette): void {
	const c = converters(d.units);
	const today = new Date().toLocaleDateString('en-US', {
		weekday: 'long',
		month: 'long',
		day: 'numeric'
	});
	const rows = d.rows.filter((r) => r.run_id != null).slice(0, OVERVIEW_MAX);
	const r = frame(
		ctx,
		shape,
		{
			eyebrow: `Snow forecast · next ${d.days} days`,
			title: 'Where the snow is',
			subtitle: today,
			note: d.generatedAt ? `Forecast from ${madeAt(d.generatedAt)}` : ''
		},
		p
	);
	if (!rows.length) {
		font(ctx, 28, 400);
		text(ctx, 'No locations picked.', r.x, r.y + 40, p.text2);
		return;
	}
	const legendH = legend(
		ctx,
		r,
		[
			{ label: 'Snow', color: p.snow },
			{ label: `${c.snowUnit === 'in' ? '6+ in' : '15+ cm'} day`, color: p.heavy },
			{ label: 'Mixed', color: p.mix },
			{ label: 'Rain', color: p.rain }
		],
		p
	);
	const totals = rows.map((row) => dailyTotals(row.periods ?? [], d.days));
	const sums = totals.map((ts) => ts.reduce((a, t) => a + t.cm, 0));
	const max = Math.max(HEAVY_CM / 3, ...totals.flat().map((t) => t.cm));
	const color: Record<PrecipKind, string> = {
		snow: p.snow,
		heavy: p.heavy,
		mix: p.mix,
		rain: p.rain,
		none: p.snow
	};
	// Every row shares the same days; take the labels from the longest.
	const days = totals.reduce((a, ts) => (ts.length > a.length ? ts : a), totals[0]);
	const n = Math.max(1, days.length);

	// Columns: one, or two on a landscape image with many rows.
	const cols = shape === 'landscape' && rows.length > LANDSCAPE_ONE_COLUMN ? 2 : 1;
	const perCol = Math.ceil(rows.length / cols);
	const colGap = 44;
	const colW = (r.w - colGap * (cols - 1)) / cols;
	const headH = 40;
	const areaH = r.h - legendH - 20;
	const rowH = (areaH - headH) / perCol;
	// Type grows and shrinks with the rows (1 at about a 95 px row), and is a size smaller
	// in a two-column image, where each column is half as wide.
	const s = clamp(rowH / 95, 0.76, 1.2);
	const two = cols === 2;
	const nameF = Math.round((two ? 25 : 30) * s);
	const regionF = Math.round((two ? 17 : 20) * s);
	const totalF = Math.round((two ? 34 : 44) * s);
	const unitF = Math.round(clamp((two ? 18 : 21) * s, 16, 24));
	const valueF = Math.round(clamp(18 * s, 15, 22));

	// Total column: as wide as the widest total.
	const nums = sums.map((cm) => (c.snow(cm) ?? 0).toFixed(c.snowDigits));
	font(ctx, unitF, 500);
	const unitW = ctx.measureText(c.snowUnit).width;
	font(ctx, totalF, 600, true);
	const totalW = Math.max(...nums.map((t) => ctx.measureText(t).width)) + 6 + unitW;
	const gap = two ? 16 : 26;
	const nameW = colW * (two ? 0.36 : 0.38);
	const barsW = colW - nameW - totalW - gap * 2;
	const slot = barsW / n;
	const barW = Math.min(slot * 0.6, 48);
	// Narrow slots get three-letter day names ("Sat" rather than "Today") in smaller type.
	const dayF = slot >= 46 ? 19 : 16;
	const dayLabel = (i: number) => {
		const t = days[i];
		return slot >= 58 || t.label !== 'Today' ? t.label : weekday(t.date);
	};

	for (let col = 0; col < cols; col++) {
		const x0 = r.x + col * (colW + colGap);
		const bx = x0 + nameW + gap;
		const totalRight = x0 + colW;

		// Header: day names over the bars and the total's unit.
		const hy = r.y + headH - 14;
		days.forEach((t, i) => {
			font(ctx, dayF, i === 0 || t.weekend ? 600 : 400);
			const tint = i === 0 ? p.text : t.weekend ? p.accent : p.text3;
			text(ctx, dayLabel(i), bx + (i + 0.5) * slot, hy, tint, 'center');
		});
		font(ctx, dayF, 400);
		text(ctx, `${d.days} days`, totalRight, hy, p.text3, 'right');

		const start = col * perCol;
		rows.slice(start, start + perCol).forEach((row, line) => {
			const k = start + line;
			const y0 = r.y + headH + line * rowH;
			ctx.fillStyle = p.border;
			ctx.fillRect(x0, y0, colW, 1.5);
			const cy = y0 + rowH / 2;

			// Name (on two lines when it's long) and region, centred in the row.
			const name = nameLines(ctx, row.name, nameW, nameF);
			const lineH = name.size * 1.12;
			const nameH = name.lines.length * lineH;
			const withRegion = nameH + 6 + regionF <= rowH - 10;
			const blockH = nameH + (withRegion ? 6 + regionF : 0);
			const top = cy - blockH / 2;
			font(ctx, name.size, 600);
			name.lines.forEach((l, j) => text(ctx, l, x0, top + j * lineH + name.size * 0.8, p.text));
			if (withRegion) {
				font(ctx, regionF, 400);
				const sub = `${row.region}${row.kind === 'backcountry' ? ' · Backcountry' : ''}`;
				text(ctx, ellipsize(ctx, sub, nameW), x0, top + nameH + 6 + regionF * 0.8, p.text3);
			}

			// Total, right-aligned with its unit.
			const zero = Number(nums[k]) === 0;
			const ty = cy + totalF * 0.36;
			font(ctx, unitF, 500);
			text(ctx, c.snowUnit, totalRight, ty, p.text2, 'right');
			font(ctx, totalF, 600, true);
			text(ctx, nums[k], totalRight - unitW - 6, ty, zero ? p.text3 : p.text, 'right');

			// Bars, with the amount above each snowy day.
			const base = y0 + rowH - Math.max(8, 12 * s);
			const barTop = y0 + Math.max(6, 8 * s) + valueF + 6;
			const bh = Math.max(12, base - barTop);
			totals[k].forEach((t, i) => {
				const cx = bx + (i + 0.5) * slot;
				const h = t.cm > 0 ? Math.max(5, (t.cm / max) * bh) : 3;
				fillRound(
					ctx,
					cx - barW / 2,
					base - h,
					barW,
					h,
					Math.min(7, barW / 3),
					t.cm > 0 ? color[t.kind] : p.border
				);
				const v = (c.snow(t.cm) ?? 0).toFixed(c.snowDigits);
				if (Number(v) > 0) {
					font(ctx, valueF, 600, true);
					text(ctx, v, cx, base - h - 6, p.text2, 'center');
				}
			});
		});
	}
}

/**
 * A location name in at most `width` px: on one line, shrinking the type a little if
 * that's enough, else over two lines (the second shortened if it still doesn't fit).
 */
function nameLines(
	ctx: Ctx,
	name: string,
	width: number,
	size: number
): { lines: string[]; size: number } {
	const small = Math.max(17, Math.round(size * 0.86));
	const f = fitSize(ctx, name, width, size, small, 600);
	if (ctx.measureText(name).width <= width) return { lines: [name], size: f };
	font(ctx, small, 600);
	const words = name.split(/\s+/);
	let first = words[0];
	let k = 1;
	while (k < words.length && ctx.measureText(`${first} ${words[k]}`).width <= width) {
		first += ` ${words[k++]}`;
	}
	const rest = words.slice(k).join(' ');
	if (!rest) return { lines: [ellipsize(ctx, first, width)], size: small };
	return { lines: [ellipsize(ctx, first, width), ellipsize(ctx, rest, width)], size: small };
}
