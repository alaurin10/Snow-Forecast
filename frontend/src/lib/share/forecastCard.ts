// Share image of the forecast chart as it is set up in the app: the chosen metric,
// range and elevation. Headline numbers on top, the chart, then its legend.
import type { BandOut } from '../types.gen';
import { converters, elevation, type UnitSystem } from '../units';
import { compass } from '../conditions';
import { dateOf, hourLabel, monthDay, weekday } from '../time';
import { buildSteps, niceAxis, STEP, type Metric, type Range, type Step } from '../charts/forecast';
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
	type LegendItem,
	type Palette,
	type Rect,
	type Shape,
	type Stat
} from './canvas';

export interface ForecastShare {
	name: string;
	region: string;
	band: BandOut;
	bands: BandOut[];
	units: UnitSystem;
	metric: Metric;
	range: Range;
	generatedAt: string;
}

export const METRIC_NAME: Record<Metric, string> = {
	precip: 'Snow and rain',
	temp: 'Temperature',
	wind: 'Wind',
	cloud: 'Cloud cover',
	fl: 'Freezing level',
	slr: 'Snow ratio'
};

const PER: Record<number, string> = { 1: 'per hour', 3: 'per 3 h', 6: 'per 6 h', 12: 'per 12 h' };

/** "Fri" for a whole-day step range, "Fri 6 AM" for shorter steps. */
function when(st: Step): string {
	const d = weekday(dateOf(st.t));
	if (st.hours === 12) return `${d} ${st.night ? 'night' : ''}`.trim();
	return `${d} ${hourLabel(st.t)}`;
}

export function rangeWords(range: number): string {
	return range === 1 ? 'next 24 hours' : `next ${range} days`;
}

export function drawForecastCard(ctx: Ctx, shape: Shape, d: ForecastShare, p: Palette): void {
	const steps = buildSteps(d.band.hourly, d.range);
	const r = frame(
		ctx,
		shape,
		{
			eyebrow: `${METRIC_NAME[d.metric]} · ${rangeWords(d.range)}`,
			title: d.name,
			subtitle: `${d.region} · ${d.band.label} ${elevation(d.band.elev_m, d.units)}`,
			note: `Forecast from ${madeAt(d.generatedAt)}`
		},
		p
	);
	if (!steps.length) {
		font(ctx, 28, 400);
		text(ctx, 'No forecast for this range yet.', r.x, r.y + 40, p.text2);
		return;
	}
	const used = statRow(ctx, r, stats(d, steps, p), p);
	const legendH = legend(ctx, r, legendItems(d, p), p);
	const chart = { x: r.x, y: r.y + used + 20, w: r.w, h: r.h - used - 20 - legendH - 18 };
	drawChart(ctx, chart, d, steps, p);
}

function stats(d: ForecastShare, steps: Step[], p: Palette): Stat[] {
	const c = converters(d.units);
	const pick = (f: (s: Step) => number | null, best: 'max' | 'min') => {
		let out: Step | null = null;
		let v: number | null = null;
		for (const s of steps) {
			const x = f(s);
			if (x === null) continue;
			if (v === null || (best === 'max' ? x > v : x < v)) {
				v = x;
				out = s;
			}
		}
		return { s: out, v };
	};
	const fmtH = (m: number | null) => elevation(m, d.units);
	if (d.metric === 'precip') {
		const total = c.snow(steps[steps.length - 1].cum) ?? 0;
		const byDay = new Map<string, number>();
		for (const s of steps) byDay.set(dateOf(s.t), (byDay.get(dateOf(s.t)) ?? 0) + s.snow);
		let bestDay = '';
		let bestCm = 0;
		for (const [day, cm] of byDay)
			if (cm > bestCm) {
				bestCm = cm;
				bestDay = day;
			}
		const rain = steps.reduce((a, s) => a + s.rain, 0);
		return [
			{
				label: 'Total snow',
				value: `${total.toFixed(c.snowDigits)} ${c.snowUnit}`,
				sub: rangeWords(d.range),
				color: p.snow
			},
			{
				label: 'Snowiest day',
				value: bestCm > 0 ? `${(c.snow(bestCm) ?? 0).toFixed(c.snowDigits)} ${c.snowUnit}` : '–',
				sub: bestCm > 0 ? `${weekday(bestDay)} ${monthDay(bestDay)}` : 'no snow'
			},
			{
				label: 'Rain',
				value: `${(c.water(rain * 10) ?? 0).toFixed(c.waterDigits)} ${c.waterUnit}`,
				sub: 'of water',
				color: p.rain
			}
		];
	}
	if (d.metric === 'temp') {
		const hi = pick((s) => c.temp(s.temp), 'max');
		const lo = pick((s) => c.temp(s.temp), 'min');
		const below = steps.filter((s) => (c.temp(s.temp) ?? 99) <= c.freezing).length;
		return [
			{
				label: 'Warmest',
				value: `${Math.round(hi.v ?? 0)}${c.tempUnit}`,
				sub: hi.s ? when(hi.s) : '',
				color: p.temp
			},
			{
				label: 'Coldest',
				value: `${Math.round(lo.v ?? 0)}${c.tempUnit}`,
				sub: lo.s ? when(lo.s) : ''
			},
			{
				label: 'Below freezing',
				value: `${Math.round((below / steps.length) * 100)}%`,
				sub: 'of the time'
			}
		];
	}
	if (d.metric === 'wind') {
		const w = pick((s) => c.speed(s.wind), 'max');
		const g = pick((s) => c.speed(s.gust), 'max');
		return [
			{
				label: 'Strongest wind',
				value: `${Math.round(w.v ?? 0)} ${c.speedUnit}`,
				sub: w.s ? `${compass(w.s.dir)} · ${when(w.s)}` : '',
				color: p.wind
			},
			{
				label: 'Peak gust',
				value: `${Math.round(g.v ?? 0)} ${c.speedUnit}`,
				sub: g.s ? when(g.s) : ''
			}
		];
	}
	if (d.metric === 'cloud') {
		const vals = steps.map((s) => s.cloud).filter((v): v is number => v !== null);
		const clear = pick((s) => s.cloud, 'min');
		return [
			{
				label: 'Average cover',
				value: `${Math.round(vals.reduce((a, b) => a + b, 0) / Math.max(1, vals.length))}%`,
				sub: rangeWords(d.range),
				color: p.cloud
			},
			{
				label: 'Clearest',
				value: `${Math.round(clear.v ?? 0)}%`,
				sub: clear.s ? when(clear.s) : ''
			}
		];
	}
	if (d.metric === 'fl') {
		const lo = pick((s) => s.fl, 'min');
		const hi = pick((s) => s.fl, 'max');
		return [
			{ label: 'Lowest', value: fmtH(lo.v), sub: lo.s ? when(lo.s) : '', color: p.level },
			{ label: 'Highest', value: fmtH(hi.v), sub: hi.s ? when(hi.s) : '' }
		];
	}
	// Snow ratio, weighted by how much snow falls.
	let w = 0;
	let sum = 0;
	for (const s of steps)
		if (s.slr !== null && s.snow > 0) {
			w += s.snow;
			sum += s.slr * s.snow;
		}
	const driest = pick((s) => (s.snow > 0.05 ? s.slr : null), 'max');
	return [
		{
			label: 'Average while snowing',
			value: w > 0 ? `${Math.round(sum / w)}:1` : '–',
			sub: w > 0 ? slrWord(sum / w) : 'no snow',
			color: p.snow
		},
		{
			label: 'Driest snow',
			value: driest.v !== null ? `${Math.round(driest.v)}:1` : '–',
			sub: driest.s ? when(driest.s) : ''
		}
	];
}

const slrWord = (v: number) =>
	v < 9.5 ? 'heavy & wet' : v < 12.5 ? 'average' : v < 15.5 ? 'light' : 'dry powder';

function legendItems(d: ForecastShare, p: Palette): LegendItem[] {
	const c = converters(d.units);
	const night: LegendItem = {
		label: 'Night',
		color: p.dark ? '#000000' : p.text,
		alpha: p.dark ? 0.5 : 0.12
	};
	switch (d.metric) {
		case 'precip':
			return [
				{ label: 'Snow', color: p.snow },
				{ label: `Snow on a ${c.snowUnit === 'in' ? '6+ in' : '15+ cm'} day`, color: p.heavy },
				{ label: 'Mixed', color: p.mix },
				{ label: `Rain (${c.waterUnit} of water)`, color: p.rain },
				{ label: 'Running total', color: p.text, line: 'solid' },
				night
			];
		case 'temp':
			return [
				{
					label: STEP[d.range] === 12 ? 'Highs and lows' : 'Temperature',
					color: p.temp,
					line: 'solid'
				},
				{ label: 'Range across models', color: p.temp, alpha: 0.2 },
				{ label: 'Freezing', color: p.text2, line: 'dashed' },
				night
			];
		case 'wind':
			return [
				{ label: 'Sustained wind', color: p.wind, line: 'solid' },
				{ label: 'Gusts', color: p.wind, line: 'dashed' },
				night
			];
		case 'cloud':
			return [{ label: 'Cloud cover', color: p.cloud, alpha: 0.6 }, night];
		case 'fl':
			return [
				{ label: 'Freezing level', color: p.level, line: 'solid' },
				{ label: 'Range across models', color: p.level, alpha: 0.2 },
				{ label: 'This location’s elevations', color: p.text2, line: 'dashed' },
				night
			];
		default:
			return [
				{ label: 'Snow ratio while snowing', color: p.snow, line: 'solid' },
				{ label: 'If it snowed', color: p.snow, line: 'dashed', alpha: 0.5 },
				night
			];
	}
}

/** The chart itself: axes, night shading, day labels and the metric's marks. */
function drawChart(ctx: Ctx, r: Rect, d: ForecastShare, steps: Step[], p: Palette): void {
	const c = converters(d.units);
	const N = steps.length;
	const precip = d.metric === 'precip';
	const titleH = 34;
	const left = 88;
	const right = precip ? 64 : 12;
	const bottom = 62;
	const plot = {
		x: r.x + left,
		y: r.y + titleH + 10,
		w: r.w - left - right,
		h: r.h - titleH - 10 - bottom
	};
	const colW = plot.w / N;
	const xAt = (k: number) => plot.x + (k + 0.5) * colW;

	// Axis titles.
	font(ctx, 21, 600);
	const unitWord = {
		precip: `Snow ${PER[STEP[d.range]]} (${c.snowUnit})`,
		temp: `Temperature (${c.tempUnit})`,
		wind: `Wind (${c.speedUnit})`,
		cloud: 'Cloud cover (%)',
		fl: `Freezing level (${c.heightUnit})`,
		slr: 'Snow-to-liquid ratio'
	}[d.metric];
	text(ctx, unitWord, r.x, r.y + 22, p.text2);
	if (precip) text(ctx, `Total (${c.snowUnit})`, r.x + r.w, r.y + 22, p.text2, 'right');

	// Scale.
	const val = (s: Step): number | null =>
		d.metric === 'precip'
			? (c.snow(s.snow) ?? 0)
			: d.metric === 'temp'
				? c.temp(s.temp)
				: d.metric === 'wind'
					? c.speed(s.wind)
					: d.metric === 'cloud'
						? s.cloud
						: d.metric === 'fl'
							? c.height(s.fl)
							: s.slr;
	const vals = steps.map(val).filter((v): v is number => v !== null);
	const elevs = d.bands.map((b) => ({ label: b.label, v: c.height(b.elev_m) ?? 0 }));
	let axis: { min: number; max: number; ticks: number[] };
	if (precip) axis = niceAxis(0, Math.max(d.units === 'imperial' ? 0.2 : 0.5, ...vals), 4);
	else if (d.metric === 'temp') {
		const spread = steps
			.flatMap((s) => [c.temp(s.tempLo), c.temp(s.tempHi)])
			.filter((v): v is number => v !== null);
		axis = niceAxis(
			Math.min(c.freezing, ...vals, ...spread) - 2,
			Math.max(c.freezing, ...vals, ...spread) + 2,
			4
		);
	} else if (d.metric === 'wind') {
		const g = steps.map((s) => c.speed(s.gust)).filter((v): v is number => v !== null);
		axis = niceAxis(0, Math.max(10, ...vals, ...g), 4);
	} else if (d.metric === 'fl') {
		const e = elevs.map((x) => x.v);
		for (const s of steps)
			for (const v of [c.height(s.flLo), c.height(s.flHi)]) if (v !== null) e.push(v);
		axis = niceAxis(Math.min(...vals, ...e) * 0.9, Math.max(...vals, ...e) * 1.05, 4);
	} else if (d.metric === 'slr') axis = { min: 4, max: 20, ticks: [5, 8, 11, 14, 17, 20] };
	else axis = { min: 0, max: 100, ticks: [0, 25, 50, 75, 100] };
	const yAt = (v: number) => plot.y + plot.h - ((v - axis.min) / (axis.max - axis.min)) * plot.h;

	// Night shading and midnight lines.
	ctx.fillStyle = p.night;
	steps.forEach((s, k) => {
		if (s.night) ctx.fillRect(plot.x + k * colW, plot.y, colW + 0.5, plot.h);
	});
	ctx.fillStyle = p.grid;
	for (let k = 1; k < N; k++)
		if (dateOf(steps[k].t) !== dateOf(steps[k - 1].t))
			ctx.fillRect(Math.round(plot.x + k * colW), plot.y, 1.5, plot.h);

	// Snow-ratio zones behind everything else.
	if (d.metric === 'slr') {
		const zones = [
			{ lo: 4, hi: 9.5, color: p.mix, a: 0.1 },
			{ lo: 9.5, hi: 12.5, color: p.snow, a: 0.07 },
			{ lo: 12.5, hi: 15.5, color: p.snow, a: 0.13 },
			{ lo: 15.5, hi: 20, color: p.snow, a: 0.2 }
		];
		for (const z of zones) {
			ctx.globalAlpha = z.a;
			ctx.fillStyle = z.color;
			ctx.fillRect(plot.x, yAt(z.hi), plot.w, yAt(z.lo) - yAt(z.hi));
		}
		ctx.globalAlpha = 1;
	}

	// Grid and left ticks.
	font(ctx, 21, 400);
	for (const t of axis.ticks) {
		const y = yAt(t);
		ctx.fillStyle = p.grid;
		ctx.fillRect(plot.x, Math.round(y), plot.w, 1.5);
		text(ctx, tickLabel(t, d.metric, d.units), plot.x - 12, y, p.text3, 'right', 'middle');
	}

	// Day (or hour) labels under the plot.
	const labelY = plot.y + plot.h + 28;
	if (d.range === 1) {
		font(ctx, 20, 500);
		steps.forEach((s, k) => {
			const hr = Number(s.t.slice(11, 13));
			if (hr % 3 === 0) text(ctx, hourShort(hr), xAt(k), labelY, p.text2, 'center');
		});
		font(ctx, 20, 400);
		text(
			ctx,
			`${weekday(dateOf(steps[0].t))} ${monthDay(dateOf(steps[0].t))}`,
			plot.x,
			labelY + 26,
			p.text3
		);
	} else {
		let k0 = 0;
		for (let k = 1; k <= N; k++)
			if (k === N || dateOf(steps[k].t) !== dateOf(steps[k0].t)) {
				const w = (k - k0) * colW;
				const day = dateOf(steps[k0].t);
				const cx = plot.x + ((k0 + k) / 2) * colW;
				if (w >= 46) {
					font(ctx, w >= 70 ? 22 : 19, 600);
					text(ctx, weekday(day), cx, labelY, p.text2, 'center');
					font(ctx, 19, 400);
					text(
						ctx,
						w >= 70 ? monthDay(day) : day.slice(8).replace(/^0/, ''),
						cx,
						labelY + 24,
						p.text3,
						'center'
					);
				}
				k0 = k;
			}
	}

	ctx.lineJoin = 'round';
	ctx.lineCap = 'round';
	if (precip) {
		const barW = Math.max(3, colW * 0.68);
		const color = { snow: p.snow, heavy: p.heavy, mix: p.mix, rain: p.rain, none: p.snow };
		const rainIn = (s: Step) => c.water(s.rain * 10) ?? 0;
		const rainMax = Math.max(d.units === 'imperial' ? 0.1 : 2.5, ...steps.map(rainIn));
		steps.forEach((s, k) => {
			const v = c.snow(s.snow) ?? 0;
			const x = xAt(k) - barW / 2;
			if (v > 0.005 && s.kind !== 'rain') {
				const top = yAt(v);
				fillRound(ctx, x, top, barW, plot.y + plot.h - top, Math.min(6, barW / 3), color[s.kind]);
			}
			if (s.kind === 'rain' && rainIn(s) >= (d.units === 'imperial' ? 0.01 : 0.2)) {
				const h = Math.max(5, (rainIn(s) / rainMax) * plot.h * 0.14);
				fillRound(ctx, x + barW * 0.2, plot.y + plot.h - h, barW * 0.6, h, 3, p.rain);
				if (colW >= 40) {
					font(ctx, 17, 600);
					text(
						ctx,
						rainIn(s).toFixed(c.waterDigits),
						xAt(k),
						plot.y + plot.h - h - 8,
						p.rain,
						'center'
					);
				}
			}
		});
		// Running total on the right axis.
		const cum = niceAxis(0, Math.max(1, c.snow(steps[N - 1].cum) ?? 1), 4);
		const yC = (v: number) => plot.y + plot.h - (v / cum.max) * (plot.h - 6);
		font(ctx, 21, 400);
		for (const t of cum.ticks)
			text(ctx, String(t), plot.x + plot.w + 12, yC(t), p.text3, 'left', 'middle');
		line(
			ctx,
			steps.map((s, k) => ({ x: xAt(k), y: yC(c.snow(s.cum) ?? 0) })),
			p.text,
			4
		);
	} else if (d.metric === 'temp' || d.metric === 'fl') {
		const color = d.metric === 'temp' ? p.temp : p.level;
		const lo = (s: Step) => (d.metric === 'temp' ? c.temp(s.tempLo) : c.height(s.flLo));
		const hi = (s: Step) => (d.metric === 'temp' ? c.temp(s.tempHi) : c.height(s.flHi));
		band(
			ctx,
			steps,
			xAt,
			(s) => lo(s),
			(s) => hi(s),
			yAt,
			color
		);
		const refs =
			d.metric === 'temp'
				? [{ label: `${c.freezing}${c.tempUnit}`, v: c.freezing }]
				: elevs.map((e) => ({
						label: `${e.label} ${elevation(d.bands.find((b) => b.label === e.label)?.elev_m, d.units)}`,
						v: e.v
					}));
		refLines(ctx, plot, refs, yAt, steps, val, xAt, p);
		line(
			ctx,
			steps.map((s, k) => pt(xAt(k), val(s), yAt)),
			color,
			5
		);
	} else if (d.metric === 'wind') {
		line(
			ctx,
			steps.map((s, k) => pt(xAt(k), c.speed(s.gust), yAt)),
			p.wind,
			3.5,
			[10, 8],
			0.8
		);
		line(
			ctx,
			steps.map((s, k) => pt(xAt(k), val(s), yAt)),
			p.wind,
			5
		);
	} else if (d.metric === 'cloud') {
		const pts = steps.map((s, k) => pt(xAt(k), val(s), yAt));
		ctx.beginPath();
		let open = false;
		let lastX = 0;
		const base = yAt(0);
		pts.forEach((q) => {
			if (!q) return;
			if (!open) {
				ctx.moveTo(q.x, base);
				open = true;
			}
			ctx.lineTo(q.x, q.y);
			lastX = q.x;
		});
		if (open) {
			ctx.lineTo(lastX, base);
			ctx.closePath();
			ctx.globalAlpha = 0.45;
			ctx.fillStyle = p.cloud;
			ctx.fill();
			ctx.globalAlpha = 1;
		}
		line(ctx, pts, p.cloud, 4);
	} else {
		// Snow ratio: solid while snow falls, faint and dashed when it is only "if it snowed".
		const all = steps.map((s, k) => pt(xAt(k), s.slr, yAt));
		line(ctx, all, p.snow, 3, [8, 7], 0.45);
		line(
			ctx,
			steps.map((s, k) => (s.snow > 0.05 ? all[k] : null)),
			p.snow,
			5
		);
	}
}

function pt(x: number, v: number | null, yAt: (v: number) => number) {
	return v === null ? null : { x, y: yAt(v) };
}

/** A line through the points, broken at gaps. */
function line(
	ctx: Ctx,
	pts: ({ x: number; y: number } | null)[],
	color: string,
	width: number,
	dash: number[] = [],
	alpha = 1
): void {
	ctx.strokeStyle = color;
	ctx.lineWidth = width;
	ctx.setLineDash(dash);
	ctx.globalAlpha = alpha;
	ctx.beginPath();
	let open = false;
	for (const q of pts) {
		if (!q) {
			open = false;
			continue;
		}
		if (open) ctx.lineTo(q.x, q.y);
		else ctx.moveTo(q.x, q.y);
		open = true;
	}
	ctx.stroke();
	// A single isolated point still shows as a dot.
	pts.forEach((q, k) => {
		if (q && !pts[k - 1] && !pts[k + 1]) {
			ctx.beginPath();
			ctx.arc(q.x, q.y, width, 0, Math.PI * 2);
			ctx.fillStyle = color;
			ctx.fill();
		}
	});
	ctx.setLineDash([]);
	ctx.globalAlpha = 1;
}

/** The model range as a soft band. */
function band(
	ctx: Ctx,
	steps: Step[],
	xAt: (k: number) => number,
	lo: (s: Step) => number | null,
	hi: (s: Step) => number | null,
	yAt: (v: number) => number,
	color: string
): void {
	const ks = steps.map((s, k) => k).filter((k) => lo(steps[k]) !== null && hi(steps[k]) !== null);
	if (ks.length < 2) return;
	ctx.beginPath();
	ks.forEach((k, i) =>
		i ? ctx.lineTo(xAt(k), yAt(hi(steps[k])!)) : ctx.moveTo(xAt(k), yAt(hi(steps[k])!))
	);
	for (const k of [...ks].reverse()) ctx.lineTo(xAt(k), yAt(lo(steps[k])!));
	ctx.closePath();
	ctx.globalAlpha = 0.14;
	ctx.fillStyle = color;
	ctx.fill();
	ctx.globalAlpha = 1;
}

/**
 * Dashed reference lines with labels. Each label sits just above or below its line at
 * the end of the plot where the data line is farther away, nudged apart from the others.
 */
function refLines(
	ctx: Ctx,
	plot: Rect,
	refs: { label: string; v: number }[],
	yAt: (v: number) => number,
	steps: Step[],
	val: (s: Step) => number | null,
	xAt: (k: number) => number,
	p: Palette
): void {
	ctx.strokeStyle = p.text2;
	ctx.globalAlpha = 0.6;
	ctx.lineWidth = 2;
	ctx.setLineDash([9, 7]);
	for (const r of refs) {
		const y = Math.round(yAt(r.v));
		ctx.beginPath();
		ctx.moveTo(plot.x, y);
		ctx.lineTo(plot.x + plot.w, y);
		ctx.stroke();
	}
	ctx.setLineDash([]);
	ctx.globalAlpha = 1;

	font(ctx, 20, 600);
	const H = 30;
	// The data line's height at x, joining the step points.
	const pts = steps
		.map((s, k) => {
			const v = val(s);
			return v === null ? null : { x: xAt(k), y: yAt(v) };
		})
		.filter((q): q is { x: number; y: number } => q !== null);
	const lineAt = (x: number) => {
		if (!pts.length) return null;
		if (x <= pts[0].x) return pts[0].y;
		for (let k = 1; k < pts.length; k++)
			if (x <= pts[k].x) {
				const a = pts[k - 1];
				const b = pts[k];
				return a.y + ((b.y - a.y) * (x - a.x)) / (b.x - a.x);
			}
		return pts[pts.length - 1].y;
	};
	// Each label takes the spot along its line, just above or below, where the data line
	// comes least close; the right-hand end wins ties.
	const placed = refs.map((r) => {
		const w = ctx.measureText(r.label).width + 18;
		const line = yAt(r.v);
		let best = { x: plot.x + plot.w - w - 8, top: line - H - 4, gap: -1 };
		for (const top of [line - H - 4, line + 4]) {
			if (top < plot.y || top + H > plot.y + plot.h) continue;
			for (let x = plot.x + plot.w - w - 8; x >= plot.x + 8; x -= 12) {
				let gap = Infinity;
				for (let xx = x - 6; xx <= x + w + 6; xx += 6) {
					const ly = lineAt(xx);
					if (ly !== null)
						gap = Math.min(gap, ly < top ? top - ly : ly > top + H ? ly - top - H : 0);
				}
				if (gap > best.gap + 3) best = { x, top, gap };
			}
		}
		return { label: r.label, w, x: best.x, top: best.top };
	});
	placed.sort((a, b) => a.top - b.top);
	for (let k = 1; k < placed.length; k++)
		for (let j = 0; j < k; j++) {
			const a = placed[k];
			const b = placed[j];
			const apart = a.x >= b.x + b.w + 6 || b.x >= a.x + a.w + 6;
			if (!apart && a.top < b.top + H + 4) a.top = b.top + H + 4;
		}
	for (const q of placed) {
		ctx.globalAlpha = 0.92;
		fillRound(ctx, q.x, q.top, q.w, H, 8, p.surface);
		ctx.globalAlpha = 1;
		text(
			ctx,
			ellipsize(ctx, q.label, plot.w - 16),
			q.x + 9,
			q.top + H / 2 + 1,
			p.text2,
			'left',
			'middle'
		);
	}
}

function tickLabel(v: number, metric: Metric, units: UnitSystem): string {
	if (metric === 'temp') return `${v}°`;
	if (metric === 'slr') return `${v}:1`;
	if (metric === 'cloud') return `${v}%`;
	if (metric === 'fl')
		return units === 'imperial'
			? `${(v / 1000).toLocaleString('en-US')}k`
			: `${(v / 1000).toLocaleString('en-US')} km`;
	return String(v);
}

function hourShort(hr: number): string {
	if (hr === 0) return '12a';
	if (hr === 12) return '12p';
	return hr < 12 ? `${hr}a` : `${hr - 12}p`;
}
