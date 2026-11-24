// Share image of the Compare chart as it's set up in the app: the metric, band and days in
// view, the locations drawn as lines (in their colours) with each one's summary for those
// days on top, and the selected location picked out as on screen.
import {
	chartAxis,
	chartLines,
	lineValues,
	LIFT_HOLD_KMH,
	METRIC_NAMES,
	summarizeSteps,
	summaryText,
	tickText,
	type BandName,
	type CompareMetric,
	type Comparison,
	type SnowTotal,
	type Timeline,
	type Win
} from '../compare';
import { STEP, type Step } from '../charts/forecast';
import { converters, elevation, type UnitSystem } from '../units';
import { dateOf, hourOf, monthDay, weekday } from '../time';
import {
	font,
	frame,
	madeAt,
	statRow,
	text,
	type Ctx,
	type Palette,
	type Rect,
	type Shape
} from './canvas';

export interface CompareShare {
	/** The group's name, or "Compare". */
	title: string;
	timeline: Timeline;
	cmp: Comparison;
	win: Win;
	units: UnitSystem;
	/** The location picked out (selected), if any. */
	selected: string | null;
	/** Each line colour (by slot), as the app shows it. */
	colors: string[];
	/** Snow as a running total from now, or from the window's first step. */
	total?: SnowTotal;
}

const BAND_WORD: Record<BandName, string> = { base: 'Base', mid: 'Mid', summit: 'Summit' };

/** What a location's number on top means, per metric. */
export const SUMMARY_WORDS: Record<CompareMetric, string> = {
	snow: 'Total snow over these days',
	temp: 'High and low over these days',
	wind: 'Top gust over these days',
	cloud: 'Average cloud cover over these days',
	fl: 'Lowest freezing level over these days',
	slr: 'Average snow ratio while snowing'
};

/** The line colours the app is showing now (the theme's), by slot. */
export function compareColors(): string[] {
	const cs = getComputedStyle(document.documentElement);
	const fall = ['#4a8fe7', '#dd6b20', '#c2479f', '#5b3fb5'];
	return fall.map((f, i) => cs.getPropertyValue(`--cmp${i + 1}`).trim() || f);
}

/** "Sat Nov 7 – Mon Nov 9" for the days in view (one date when they're all one day). */
export function windowWords(steps: Step[]): string {
	if (!steps.length) return '';
	const day = (iso: string) => `${weekday(dateOf(iso))} ${monthDay(dateOf(iso))}`;
	const a = day(steps[0].t);
	const b = day(steps[steps.length - 1].t);
	return a === b ? a : `${a} – ${b}`;
}

export function drawCompareCard(ctx: Ctx, shape: Shape, d: CompareShare, p: Palette): void {
	const m = d.cmp.metric;
	const steps = d.timeline.slots.slice(d.win.off, d.win.off + d.win.n);
	const lines = chartLines(d.timeline, d.cmp);
	const r = frame(
		ctx,
		shape,
		{
			eyebrow: `${METRIC_NAMES[m].long} · ${BAND_WORD[d.cmp.band]} · ${
				d.cmp.range === 1 ? '24 hours' : `${d.cmp.range} days`
			}`,
			title: d.title,
			subtitle: windowWords(steps),
			note: d.timeline.ref ? `Forecast from ${madeAt(d.timeline.ref.generatedAt)}` : ''
		},
		p
	);
	if (!lines.length || !steps.length) {
		font(ctx, 28, 400);
		text(ctx, 'No lines drawn in this comparison.', r.x, r.y + 40, p.text2);
		return;
	}
	// Each line on top: its name in its colour, its number for the days shown, its height.
	const used = statRow(
		ctx,
		r,
		lines.map(({ slot, track }) => ({
			label: track.name,
			value: summaryText(
				summarizeSteps(track.steps.slice(d.win.off, d.win.off + d.win.n)),
				m,
				d.units
			),
			sub: `${track.band.label} · ${elevation(track.band.elev_m, d.units)}`,
			color: d.colors[slot]
		})),
		p
	);
	font(ctx, 21, 400);
	text(ctx, SUMMARY_WORDS[m], r.x, r.y + used + 8, p.text3);
	const top = used + 36;
	drawChart(ctx, { x: r.x, y: r.y + top, w: r.w, h: r.h - top }, d, steps, p);
}

function drawChart(ctx: Ctx, r: Rect, d: CompareShare, steps: Step[], p: Palette): void {
	const m = d.cmp.metric;
	const c = converters(d.units);
	const lines = chartLines(d.timeline, d.cmp);
	const N = steps.length;
	const titleH = 34;
	const left = 104;
	const right = 18;
	const bottom = 62;
	const plot = {
		x: r.x + left,
		y: r.y + titleH + 10,
		w: r.w - left - right,
		h: r.h - titleH - 10 - bottom
	};
	const colW = plot.w / N;
	const xAt = (k: number) => plot.x + (k + 0.5) * colW;
	const axis = chartAxis(
		lines.map((l) => l.track),
		m,
		d.win,
		d.units,
		d.total ?? 'run'
	);
	const yAt = (v: number) => {
		const y = plot.y + plot.h - ((v - axis.min) / (axis.max - axis.min)) * plot.h;
		return Math.min(plot.y + plot.h, Math.max(plot.y, y));
	};

	// Axis title, as on screen.
	font(ctx, 21, 600);
	const title = {
		snow: `Snow from ${d.total !== 'window' || d.win.off === 0 ? 'now' : 'the first day shown'} (${c.snowUnit})`,
		temp: `Temperature (${c.tempUnit})`,
		wind: `Wind gusts (${c.speedUnit})`,
		cloud: 'Cloud cover (% of the sky)',
		fl: `Freezing level (${c.heightUnit}); a tick marks each location's elevation`,
		slr: 'Snow ratio (inches of snow from an inch of water)'
	}[m];
	text(ctx, title, r.x, r.y + 22, p.text2);

	// Night shading (1 and 3 days, as in the app) and the lines between days.
	ctx.fillStyle = p.night;
	if (STEP[d.cmp.range] < 6)
		steps.forEach((s, k) => {
			if (s.night) ctx.fillRect(plot.x + k * colW, plot.y, colW + 0.5, plot.h);
		});
	ctx.fillStyle = p.grid;
	for (let k = 1; k < N; k++)
		if (dateOf(steps[k].t) !== dateOf(steps[k - 1].t))
			ctx.fillRect(Math.round(plot.x + k * colW), plot.y, 1.5, plot.h);

	// Snow-ratio zones behind everything else.
	if (m === 'slr') {
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

	// Grid and ticks.
	font(ctx, 21, 400);
	for (const t of axis.ticks) {
		const y = yAt(t);
		ctx.fillStyle = p.grid;
		ctx.fillRect(plot.x, Math.round(y), plot.w, 1.5);
		text(ctx, tickText(t, m, d.units), plot.x - 12, y, p.text3, 'right', 'middle');
	}

	// Reference lines: freezing on temperature, the lift-hold gust on wind.
	const ref = (v: number, label: string) => {
		const y = yAt(v);
		ctx.strokeStyle = p.text3;
		ctx.lineWidth = 2;
		ctx.setLineDash([8, 7]);
		ctx.beginPath();
		ctx.moveTo(plot.x, y);
		ctx.lineTo(plot.x + plot.w, y);
		ctx.stroke();
		ctx.setLineDash([]);
		font(ctx, 19, 500);
		text(ctx, label, plot.x + 8, y - 10, p.text2);
	};
	if (m === 'temp') ref(c.freezing, `${c.freezing}°`);
	if (m === 'wind') {
		const hold = c.speed(LIFT_HOLD_KMH) ?? 0;
		if (hold <= axis.max) ref(hold, 'Lift holds likely');
	}

	// Day (or hour) labels under the plot.
	const labelY = plot.y + plot.h + 28;
	if (d.cmp.range === 1) {
		font(ctx, 20, 500);
		steps.forEach((s, k) => {
			const hr = hourOf(s.t);
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

	// Freezing level: each location's elevation as a tick on the plot's right edge.
	if (m === 'fl')
		for (const { slot, track } of lines) {
			const y = yAt(c.height(track.band.elev_m) ?? 0);
			ctx.fillStyle = d.colors[slot];
			ctx.fillRect(plot.x + plot.w - 22, y - 3, 22, 6);
		}

	// The lines: the selected one on top and bolder, the others stepped back.
	const sel = d.selected && lines.some((l) => l.track.id === d.selected) ? d.selected : null;
	const order = [...lines].sort((a, b) => Number(a.track.id === sel) - Number(b.track.id === sel));
	ctx.lineJoin = 'round';
	ctx.lineCap = 'round';
	for (const { slot, track } of order) {
		const vals = lineValues(track, m, d.win, d.units, d.total ?? 'run');
		ctx.globalAlpha = sel && track.id !== sel ? 0.28 : 1;
		ctx.strokeStyle = d.colors[slot];
		ctx.lineWidth = track.id === sel ? 7 : 4.5;
		ctx.beginPath();
		let pen = false;
		vals.forEach((v, k) => {
			if (v === null) {
				pen = false;
				return;
			}
			if (pen) ctx.lineTo(xAt(k), yAt(v));
			else ctx.moveTo(xAt(k), yAt(v));
			pen = true;
		});
		ctx.stroke();
	}
	ctx.globalAlpha = 1;
}

function hourShort(hr: number): string {
	if (hr === 0) return '12a';
	if (hr === 12) return '12p';
	return hr < 12 ? `${hr}a` : `${hr - 12}p`;
}
