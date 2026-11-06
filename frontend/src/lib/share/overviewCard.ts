// Share image of the Overview: every location's next 7 days of snow as a row of bars,
// on one shared scale so the rows compare, with each location's total.
import type { OverviewRow } from '../types.gen';
import { dailyTotals, HEAVY_CM, type PrecipKind } from '../daybars';
import { converters, type UnitSystem } from '../units';
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

export interface OverviewShare {
	rows: OverviewRow[];
	units: UnitSystem;
	days: number;
	generatedAt: string;
}

export function drawOverviewCard(ctx: Ctx, shape: Shape, d: OverviewShare, p: Palette): void {
	const c = converters(d.units);
	const today = new Date().toLocaleDateString('en-US', {
		weekday: 'long',
		month: 'long',
		day: 'numeric'
	});
	const rows = d.rows.filter((r) => r.run_id != null);
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
		text(ctx, 'No forecasts yet.', r.x, r.y + 40, p.text2);
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
	const max = Math.max(HEAVY_CM / 3, ...totals.flat().map((t) => t.cm));
	const color: Record<PrecipKind, string> = {
		snow: p.snow,
		heavy: p.heavy,
		mix: p.mix,
		rain: p.rain,
		none: p.snow
	};

	// Portrait: one row per location (name, region and total on the left, bars on the
	// right). Landscape: a two-column grid of tiles (name and total on top, bars below), so
	// the bars keep their height on a short image.
	const wide = shape === 'landscape';
	const cols = wide && rows.length > 1 ? 2 : 1;
	const gridRows = Math.ceil(rows.length / cols);
	const gap = wide ? 36 : 0;
	const cellW = (r.w - gap * (cols - 1)) / cols;
	const cellH = (r.h - legendH - 16) / gridRows;
	rows.forEach((row, k) => {
		const col = k % cols;
		const line = Math.floor(k / cols);
		const x0 = r.x + col * (cellW + gap);
		const y0 = r.y + line * cellH;
		if (line) {
			ctx.fillStyle = p.border;
			ctx.fillRect(x0, y0, cellW, 1.5);
		}
		const sum = totals[k].reduce((a, t) => a + t.cm, 0);
		const num = (c.snow(sum) ?? 0).toFixed(c.snowDigits);
		font(ctx, 22, 500);
		const unitW = ctx.measureText(c.snowUnit).width;
		font(ctx, wide ? 40 : 46, 600, true);
		const numW = ctx.measureText(num).width;
		const totalW = numW + 6 + unitW;
		const nameW = wide ? cellW - totalW - 24 : cellW * 0.38 - 20;
		const nameY = y0 + (wide ? 40 : 46);
		fitSize(ctx, row.name, nameW, wide ? 28 : 30, 20, 600);
		text(ctx, ellipsize(ctx, row.name, nameW), x0, nameY, p.text);
		font(ctx, 20, 400);
		const sub = `${row.region}${row.kind === 'backcountry' ? ' · Backcountry' : ''}`;
		text(ctx, ellipsize(ctx, sub, nameW), x0, nameY + 27, p.text3);
		const totalRight = wide ? x0 + cellW : x0 + totalW;
		const totalY = wide ? nameY + 4 : nameY + 84;
		font(ctx, wide ? 40 : 46, 600, true);
		text(ctx, num, totalRight - unitW - 6, totalY, p.text, 'right');
		font(ctx, 22, 500);
		text(ctx, c.snowUnit, totalRight, totalY, p.text2, 'right');

		// Bars for each day.
		const bx = wide ? x0 : x0 + cellW * 0.38;
		const bw = wide ? cellW : cellW * 0.62;
		const base = y0 + cellH - 40;
		const barTop = wide ? nameY + 62 : y0 + 40;
		const bh = Math.max(20, base - barTop);
		const n = totals[k].length;
		const slot = bw / Math.max(1, n);
		totals[k].forEach((t, i) => {
			const cx = bx + (i + 0.5) * slot;
			const w = Math.min(slot * 0.62, 64);
			const h = t.cm > 0 ? Math.max(5, (t.cm / max) * bh) : 3;
			fillRound(
				ctx,
				cx - w / 2,
				base - h,
				w,
				h,
				Math.min(7, w / 3),
				t.cm > 0 ? color[t.kind] : p.border
			);
			if (t.cm >= 0.25) {
				font(ctx, 19, 600, true);
				text(ctx, (c.snow(t.cm) ?? 0).toFixed(c.snowDigits), cx, base - h - 8, p.text2, 'center');
			}
			font(ctx, 18, t.weekend ? 600 : 400);
			text(ctx, t.label, cx, base + 26, t.weekend ? p.accent : p.text3, 'center');
		});
	});
}
