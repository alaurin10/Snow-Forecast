<!-- One chart for every metric. Cards above it switch the metric and show each value at
     the hovered step; the range picker sets both the span and the step size. Every
     piece of text has a fixed size so sweeping across the chart never moves the layout.
     Precipitation keeps snow (above the line, inches of snow) apart from rain (below the
     line, inches of water) because the two kinds of inch are not comparable. -->
<script lang="ts">
	import type { BandOut } from '../types.gen';
	import { converters, elevation, speed, type UnitSystem } from '../units';
	import { compass } from '../conditions';
	import { dateOf, hourLabel, hourOf, monthDay, weekday } from '../time';
	import {
		availableRanges,
		buildSteps,
		niceAxis,
		STEP,
		type Metric,
		type Range,
		type Step
	} from './forecast';
	import ShareButton from '../share/ShareButton.svelte';
	import { paint, slug } from '../share/canvas';
	import { drawForecastCard, METRIC_NAME } from '../share/forecastCard';

	interface Props {
		band: BandOut;
		/** All bands, for the base, mid and summit lines on the freezing-level view. */
		bands: BandOut[];
		units: UnitSystem;
		/** Click on a step: the time of its first hour. */
		onpick?: (t: string) => void;
		/** Days shown; bindable so the page header can change it too. */
		range?: Range;
		/** The location, for sharing the chart as an image; no share button without it. */
		place?: { name: string; region: string; generatedAt: string };
	}

	let { band, bands, units, onpick, range = $bindable(5), place }: Props = $props();
	const c = $derived(converters(units));
	const ranges = $derived(availableRanges(band.hourly.t.length));
	let metric = $state<Metric>('precip');
	let hoverT = $state<string | null>(null);
	const R = $derived<Range>(ranges.includes(range) ? range : (ranges[ranges.length - 1] ?? 1));
	const steps = $derived(buildSteps(band.hourly, R));
	const N = $derived(Math.max(1, steps.length));
	const W = $derived(1000 / N);
	const H = 300;

	// The hovered step keeps its time across range changes.
	const hv = $derived.by(() => {
		if (!steps.length) return 0;
		const t = hoverT ? Date.parse(hoverT) : NaN;
		if (Number.isNaN(t)) return Math.min(steps.length - 1, Math.floor(steps.length / 4));
		let k = steps.findIndex((s) => Date.parse(s.t) > t) - 1;
		if (k < 0) k = Date.parse(steps[0].t) > t ? 0 : steps.length - 1;
		return k;
	});
	const s = $derived<Step | undefined>(steps[hv]);

	const per: Record<number, string> = { 1: 'per hour', 3: 'per 3 h', 6: 'per 6 h', 12: 'per 12 h' };
	const resolution: Record<number, string> = {
		1: 'Hourly',
		3: 'Every 3 hours',
		6: 'Every 6 hours',
		12: 'Day and night'
	};

	const elevs = $derived(bands.map((b) => ({ label: b.label, m: b.elev_m })));
	const toPct = (yy: number) => `${((yy / H) * 100).toFixed(2)}%`;

	// Precipitation: snow owns the scale (inches of snow). Rain is never put on it: it shows
	// as small marks along the bottom, labelled with the real inches of water.
	const snowIn = (st: Step) => c.snow(st.snow) ?? 0;
	const rainIn = (st: Step) => c.water(st.rain * 10) ?? 0;
	const pAx = $derived(
		niceAxis(0, Math.max(units === 'imperial' ? 0.2 : 0.5, ...steps.map(snowIn)), 4)
	);
	const RAIN_H = 36; // tallest rain mark, in chart units (out of 300)
	const rainy = (st: Step) => rainIn(st) >= (units === 'imperial' ? 0.01 : 0.2);
	// Only all-rain steps get a green mark; snow and mixed steps show just their snow.
	const rainOnly = (st: Step) => st.kind === 'rain' && rainy(st);
	const rainMax = $derived(Math.max(units === 'imperial' ? 0.1 : 2.5, ...steps.map(rainIn)));
	const rainH = (st: Step) => Math.max(3, (rainIn(st) / rainMax) * RAIN_H);
	const showRain = $derived(metric === 'precip' || metric === 'slr');
	const rainBox = (_st: Step, k: number) => {
		const rw = W * 0.5;
		return { x: k * W + (W - rw) / 2, rw };
	};
	const rainMarks = $derived(
		showRain
			? steps
					.map((st, k) => ({ st, k }))
					.filter(({ st }) => rainOnly(st))
					.map(({ st, k }) => ({
						left: `${(((rainBox(st, k).x + rainBox(st, k).rw / 2) / 1000) * 100).toFixed(2)}%`,
						top: toPct(H - rainH(st)),
						label: rainIn(st).toFixed(c.waterDigits)
					}))
			: []
	);
	// Snow ratio zones (the backend's bands: 8, 11, 14 and 17 to 1).
	const ZONES = [
		{ lo: 4, hi: 9.5, name: 'Heavy & wet', cls: 'z-wet' },
		{ lo: 9.5, hi: 12.5, name: 'Average', cls: 'z-avg' },
		{ lo: 12.5, hi: 15.5, name: 'Light', cls: 'z-light' },
		{ lo: 15.5, hi: 20, name: 'Dry powder', cls: 'z-dry' }
	];
	const slrWord = (v: number) =>
		v < 9.5 ? 'heavy & wet' : v < 12.5 ? 'average' : v < 15.5 ? 'light' : 'dry powder';
	const yP = (v: number) => H - (v / pAx.max) * (H - 4);
	const cumAxis = $derived(
		niceAxis(0, Math.max(1, c.snow(steps[steps.length - 1]?.cum ?? 0) ?? 1), 4)
	);
	const yCum = (v: number) => H - (v / cumAxis.max) * (H - 4);

	// Scale for the other metrics, in display units.
	const view = $derived.by(() => {
		const val = (st: Step): number | null => {
			if (metric === 'precip') return snowIn(st);
			if (metric === 'slr') return st.slr;
			if (metric === 'temp') return c.temp(st.temp);
			if (metric === 'wind') return c.speed(st.wind);
			if (metric === 'cloud') return st.cloud;
			return c.height(st.fl);
		};
		const vals = steps.map(val).filter((v): v is number => v !== null);
		let axis;
		if (metric === 'temp') {
			const spread = steps
				.flatMap((st) => [c.temp(st.tempLo), c.temp(st.tempHi)])
				.filter((v): v is number => v !== null);
			const lo = Math.min(c.freezing, ...vals, ...spread);
			const hi = Math.max(c.freezing, ...vals, ...spread);
			axis = niceAxis(lo - 2, hi + 2, 4);
		} else if (metric === 'wind') {
			const g = steps.map((st) => c.speed(st.gust)).filter((v): v is number => v !== null);
			axis = niceAxis(0, Math.max(10, ...vals, ...g), 4);
		} else if (metric === 'fl') {
			const e = elevs.map((x) => c.height(x.m) ?? 0);
			for (const st of steps)
				for (const v of [c.height(st.flLo), c.height(st.flHi)]) if (v !== null) e.push(v);
			axis = niceAxis(Math.min(...vals, ...e) * 0.9, Math.max(...vals, ...e) * 1.05, 4);
		} else if (metric === 'slr') axis = { min: 4, max: 20, ticks: [5, 8, 11, 14, 17, 20] };
		else axis = { min: 0, max: 100, ticks: [0, 25, 50, 75, 100] };
		return { val, axis };
	});
	const y = (v: number) => H - ((v - view.axis.min) / (view.axis.max - view.axis.min)) * H;
	const tickLabel = (v: number) => {
		if (metric === 'temp') return `${v}°`;
		if (metric === 'slr') return `${v}:1`;
		if (metric === 'fl')
			return units === 'imperial'
				? `${(v / 1000).toLocaleString('en-US')}k ft`
				: `${v.toLocaleString('en-US')} m`;
		return `${v}`;
	};
	const axisTitle = $derived(
		{
			precip: `Snow ${per[STEP[R]]} (${c.snowUnit})`,
			slr: 'Snow ratio (inches of snow from an inch of water)',
			temp: `Temperature (${c.tempUnit})`,
			wind: `Wind (${c.speedUnit})`,
			cloud: 'Cloud by height: thicker = more of the sky covered',
			fl: `Freezing level (${c.heightUnit})`
		}[metric]
	);

	// Cloud by height: three lanes (high on top); each band's thickness is its cover.
	const LANES = $derived([
		{ name: 'High', sub: units === 'imperial' ? '26k+ ft' : '8+ km', key: 'cloudHigh', y0: 4 },
		{ name: 'Mid', sub: units === 'imperial' ? '10–26k' : '3–8 km', key: 'cloudMid', y0: 102 },
		{
			name: 'Low',
			sub: units === 'imperial' ? '<10k ft' : '<3 km',
			key: 'cloudLow',
			y0: 200
		}
	] as const);
	const LANE_H = 96;

	// Left-axis labels; each also draws a grid line.
	const yticks = $derived.by(() => {
		if (metric === 'cloud')
			return LANES.map((l) => ({ label: l.name, sub: l.sub, y: l.y0 + LANE_H / 2, cls: 'lane' }));
		if (metric === 'precip')
			return pAx.ticks.map((v) => ({ label: `${v} ${c.snowUnit}`, sub: '', y: yP(v), cls: '' }));
		return view.axis.ticks.map((v) => ({ label: tickLabel(v), sub: '', y: y(v), cls: '' }));
	});
	const grid = $derived(yticks.map((t) => `M0 ${t.y.toFixed(1)}H1000`).join(''));

	const linePath = (f: (st: Step) => number | null, yf: (v: number) => number) => {
		let p = '';
		let pen = false;
		steps.forEach((st, k) => {
			const v = f(st);
			if (v === null) {
				pen = false;
				return;
			}
			p += `${pen ? 'L' : 'M'}${(k * W + W / 2).toFixed(1)} ${yf(v).toFixed(1)}`;
			pen = true;
		});
		return p;
	};

	const paths = $derived.by(() => {
		const bars: Record<string, string> = { snow: '', heavy: '', mix: '', rain: '' };
		let line = '';
		let line2 = '';
		let band = '';
		const clouds: string[] = [];
		let faint = '';
		const zones: { y: number; h: number; cls: string }[] = [];
		if (showRain) {
			// Rain: short solid marks on their own small scale, never on the snow axis.
			steps.forEach((st, k) => {
				if (!rainOnly(st)) return;
				const hh = rainH(st);
				const { x, rw } = rainBox(st, k);
				bars.rain += `M${x.toFixed(2)} ${(H - hh).toFixed(1)}h${rw.toFixed(2)}V${H}h-${rw.toFixed(2)}z`;
			});
		}
		if (metric === 'precip') {
			const bw = W * 0.72;
			steps.forEach((st, k) => {
				// Snow only: mixed steps show their snow part; their rain is a rain mark.
				const v = snowIn(st);
				const kind = st.kind === 'rain' || st.kind === 'none' ? null : st.kind;
				if (!kind || H - yP(v) < 0.3) return;
				const x = k * W + W * 0.14;
				bars[kind] +=
					`M${x.toFixed(2)} ${yP(v).toFixed(1)}h${bw.toFixed(2)}V${H}h-${bw.toFixed(2)}z`;
			});
			line = linePath((st) => c.snow(st.cum), yCum);
		} else if (metric === 'slr') {
			for (const z of ZONES) zones.push({ y: y(z.hi), h: y(z.lo) - y(z.hi), cls: z.cls });
			// Solid where snow is falling, faint where it is dry (the ratio if it snowed).
			const at = (k: number) =>
				`${(k * W + W / 2).toFixed(1)} ${y(steps[k].slr as number).toFixed(1)}`;
			for (let k = 1; k < steps.length; k++) {
				if (steps[k - 1].slr === null || steps[k].slr === null) continue;
				const seg = `M${at(k - 1)}L${at(k)}`;
				if (steps[k - 1].snow > 0.05 || steps[k].snow > 0.05) line += seg;
				else faint += seg;
			}
		} else if (metric === 'cloud') {
			for (const l of LANES) {
				const mid = l.y0 + LANE_H / 2;
				const half = (st: Step) => ((st[l.key] ?? 0) / 100) * (LANE_H / 2 - 2);
				const pts = steps.map((st, k) => ({ x: k * W + W / 2, h: half(st) }));
				if (!pts.length) continue;
				const first = pts[0];
				const last = pts[pts.length - 1];
				const top = [{ x: 0, h: first.h }, ...pts, { x: 1000, h: last.h }];
				clouds.push(
					top
						.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${(mid - p.h).toFixed(1)}`)
						.join('') +
						[...top]
							.reverse()
							.map((p) => `L${p.x.toFixed(1)} ${(mid + p.h).toFixed(1)}`)
							.join('') +
						'Z'
				);
			}
		} else {
			line = linePath(view.val, y);
			if (metric === 'wind') line2 = linePath((st) => c.speed(st.gust), y);
		}
		// Model spread as a soft band behind the line.
		const spread =
			metric === 'temp'
				? (st: Step) => [c.temp(st.tempLo), c.temp(st.tempHi)]
				: metric === 'fl'
					? (st: Step) => [c.height(st.flLo), c.height(st.flHi)]
					: null;
		if (spread) {
			const ok = steps
				.map((st, k) => ({ x: k * W + W / 2, r: spread(st) }))
				.filter((p) => p.r[0] !== null && p.r[1] !== null);
			if (ok.length > 1)
				band =
					ok
						.map((p, k) => `${k ? 'L' : 'M'}${p.x.toFixed(1)} ${y(p.r[1] as number).toFixed(1)}`)
						.join('') +
					[...ok]
						.reverse()
						.map((p) => `L${p.x.toFixed(1)} ${y(p.r[0] as number).toFixed(1)}`)
						.join('') +
					'Z';
		}
		return { bars, line, line2, band, clouds, faint, zones };
	});

	// Lower panel (wide screens): cloud cover as a faint area, chance of precipitation as bars.
	const lower = $derived.by(() => {
		const H2 = 100;
		const at = (k: number) => (k * W + W / 2).toFixed(1);
		const cl = steps
			.map((st, k) => (st.cloud === null ? null : `${at(k)} ${(H2 - st.cloud).toFixed(1)}`))
			.filter((p): p is string => p !== null);
		const cloud = cl.length
			? `M${(W / 2).toFixed(1)} ${H2}L${cl.join('L')}L${(1000 - W / 2).toFixed(1)} ${H2}Z`
			: '';
		// Chance of precipitation as thin neutral bars, so it reads apart from the main chart.
		let pop = '';
		const pw = Math.min(W * 0.3, 14);
		steps.forEach((st, k) => {
			const hh = st.pop ?? 0;
			if (hh > 0.5)
				pop += `M${(k * W + (W - pw) / 2).toFixed(2)} ${(H2 - hh).toFixed(1)}h${pw.toFixed(2)}V${H2}h-${pw.toFixed(2)}z`;
		});
		const shadeL = steps
			.map((st, k) =>
				st.night ? `M${(k * W).toFixed(2)} 0h${W.toFixed(2)}v${H2}h-${W.toFixed(2)}z` : ''
			)
			.join('');
		return { cloud, pop, shade: shadeL };
	});
	const shade = $derived(
		steps
			.map((st, k) =>
				st.night ? `M${(k * W).toFixed(2)} 0h${W.toFixed(2)}v${H}h-${W.toFixed(2)}z` : ''
			)
			.join('')
	);
	const span = $derived(N * STEP[R]);
	const i0 = $derived(steps[0]?.i0 ?? 0);
	const pos = (i: number) => (i - i0) / span;
	const midnights = $derived.by(() => {
		let p = '';
		for (let i = i0 + 1; i < i0 + span; i++)
			if (band.hourly.t[i] && hourOf(band.hourly.t[i]) === 0)
				p += `M${(pos(i) * 1000).toFixed(1)} 0V${H}`;
		return p;
	});
	// Reference lines (freezing; this location's elevations) and their labels. Each label
	// tries its full name, then a short name, then the elevation alone, and keeps the longest
	// that fits beside its line (just above or below it) in a spot the data line stays clear
	// of. Then labels are nudged apart so close elevations never overprint.
	let plotH = $state(280);
	let plotW = $state(600);
	const LABEL_H = 15; // px
	let measureCtx: CanvasRenderingContext2D | null = null;
	/** Width (px) of a label: name in the UI font, elevation in bold numerals, plus padding. */
	const labelW = (name: string, elev: string) => {
		if (!measureCtx && typeof document !== 'undefined')
			measureCtx = document.createElement('canvas').getContext('2d');
		const m = measureCtx;
		const fallback = 12 + name.length * 5.6 + elev.length * 6.2;
		if (!m) return fallback;
		m.font = '500 10px Inter, system-ui, sans-serif';
		const a = name ? m.measureText(name).width : 0;
		m.font = "600 10px 'Space Grotesk', Inter, system-ui, sans-serif";
		const b = elev ? m.measureText(elev).width : 0;
		return Math.ceil(a + b + (name && elev ? 4 : 0) + 12);
	};
	/** "Rainy Pass trailhead" → "Rainy Pass": as few leading words as keep names apart. */
	const shortNames = (names: string[]) =>
		names.map((n) => {
			const words = n.split(/\s+/);
			for (let k = 1; k < words.length; k++) {
				const short = words.slice(0, k).join(' ');
				const clash = names.some((o) => o !== n && o.split(/\s+/).slice(0, k).join(' ') === short);
				if (!clash && short.length >= 4) return short;
			}
			return n;
		});
	const refs = $derived.by(() => {
		const shorts = shortNames(elevs.map((e) => e.label));
		const raw =
			metric === 'temp'
				? [{ key: 'freezing', options: [[`${c.freezing}${c.tempUnit}`, '']], y: y(c.freezing) }]
				: metric === 'fl'
					? elevs.map((e, i) => {
							// Longest first: "Roundhouse 6,050 ft", then without the unit (the axis
							// gives it), then a short name.
							const full = elevation(e.m, units);
							const bare = full.replace(/\s*(ft|m)$/, '');
							const names = [...new Set([e.label, shorts[i]])];
							const options = [
								...names.flatMap((n) => [
									[n, full],
									[n, bare]
								]),
								// Then the name alone (the axis gives the height), and last the number.
								...names.map((n) => [n, '']),
								['', full]
							];
							return { key: e.label, options, y: y(c.height(e.m) ?? 0) };
						})
					: [];
		if (!raw.length) return [];
		const px = (yy: number) => (yy / H) * plotH;
		// The data line's height (px) at x, joining the step points.
		const pts = steps
			.map((st, k) => {
				const v = view.val(st);
				return v === null ? null : { x: ((k + 0.5) / N) * plotW, y: px(y(v)) };
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
		// How close the data line comes to a label box.
		const gapTo = (x: number, w: number, top: number) => {
			let gap = Infinity;
			for (let xx = x - 4; xx <= x + w + 4; xx += 4) {
				const ly = lineAt(xx);
				if (ly === null) continue;
				gap = Math.min(gap, ly < top ? top - ly : ly > top + LABEL_H ? ly - top - LABEL_H : 0);
			}
			return gap;
		};
		const clampTop = (t: number) => Math.min(Math.max(t, 1), plotH - LABEL_H - 1);
		// The best spot for a label of width w: above first, right-hand end first on ties.
		const spot = (line: number, w: number) => {
			let best = { x: plotW - w - 4, top: clampTop(line - LABEL_H - 2), gap: -1 };
			for (const top of [clampTop(line - LABEL_H - 2), clampTop(line + 3)])
				for (let x = plotW - w - 4; x >= 4; x -= 6) {
					const gap = gapTo(x, w, top);
					if (gap > best.gap + 2) best = { x, top, gap };
				}
			return best;
		};
		const CLEAR = 2; // px between a label and the data line
		const placed = raw.map((r) => {
			const line = px(r.y);
			let pick: {
				name: string;
				elev: string;
				w: number;
				x: number;
				top: number;
				gap: number;
			} | null = null;
			for (const [name, elev] of r.options) {
				const w = Math.min(labelW(name, elev), plotW - 8);
				const at = spot(line, w);
				const option = { name, elev, w, ...at };
				if (at.gap >= CLEAR) {
					pick = option;
					break;
				}
				// Nothing fits cleanly: keep the shortest, which covers the least.
				pick = option;
			}
			return { key: r.key, line: r.y, ...pick! };
		});
		// Nudge apart labels that would overprint, top to bottom.
		placed.sort((a, b) => a.top - b.top);
		for (let k = 1; k < placed.length; k++) {
			const p = placed[k];
			for (let j = 0; j < k; j++) {
				const q = placed[j];
				const sideBySide = p.x >= q.x + q.w + 4 || q.x >= p.x + p.w + 4;
				if (!sideBySide && p.top < q.top + LABEL_H + 2) p.top = q.top + LABEL_H + 2;
			}
		}
		const over = Math.max(0, ...placed.map((p) => p.top + LABEL_H + 1 - plotH));
		return placed.map((p) => ({
			key: p.key,
			name: p.name,
			elev: p.elev,
			top: toPct(p.line),
			labelTop: `${(p.top - over).toFixed(1)}px`,
			labelLeft: `${p.x.toFixed(1)}px`
		}));
	});
	// Days 6 and on are less certain.
	const conf = $derived.by(() => {
		const p = pos(120);
		return p > 0 && p < 1 ? { left: `${(p * 100).toFixed(2)}%`, roomy: p < 0.85 } : null;
	});

	const clock = (hr: number) =>
		hr === 0 ? '12 AM' : hr < 12 ? `${hr} AM` : hr === 12 ? 'Noon' : `${hr - 12} PM`;
	const xlabels = $derived.by(() => {
		const out: { left: string; name: string; sub: string; strong: boolean; minor?: boolean }[] = [];
		const t = band.hourly.t;
		const at = (i: number) => `${(pos(i) * 100).toFixed(2)}%`;
		for (let i = i0; i < i0 + span && i < t.length; i++) {
			const hr = hourOf(t[i]);
			if (R === 1) {
				if (i > i0 && hr % 3 === 0)
					out.push({ left: at(i), name: clock(hr), sub: '', strong: false, minor: hr % 6 !== 0 });
			} else if (R === 3) {
				if (hr === 0 && i > i0)
					out.push({
						left: at(i),
						name: weekday(dateOf(t[i])),
						sub: monthDay(dateOf(t[i])),
						strong: true
					});
				else if (hr === 12) out.push({ left: at(i), name: 'Noon', sub: '', strong: false });
			} else if (hr === 12) {
				const d = dateOf(t[i]);
				out.push({
					left: at(i),
					name: weekday(d),
					sub: R >= 10 ? String(Number(d.slice(8))) : monthDay(d),
					strong: true
				});
			}
		}
		return out;
	});

	const when = (st: Step) => {
		const d = `${weekday(dateOf(st.t))} ${monthDay(dateOf(st.t))}`;
		if (st.hours === 1) return `${d} · ${hourLabel(st.t)}`;
		if (st.hours === 12) return `${d} · ${st.night ? 'night, 6 PM–6 AM' : 'day, 6 AM–6 PM'}`;
		const end = band.hourly.t[st.i0 + st.hours];
		return `${d} · ${hourLabel(st.t)}–${end ? hourLabel(end) : ''}`;
	};
	const zone = (m: number | null) => {
		if (m === null || !elevs.length) return '';
		const lo = elevs[0].m;
		const hi = elevs[elevs.length - 1].m;
		return m < lo ? 'below base' : m > hi ? 'above summit' : 'between base and summit';
	};
	const snowTxt = (st: Step) =>
		`${snowIn(st).toFixed(STEP[R] <= 3 ? c.snowDigits + 1 : c.snowDigits)} ${c.snowUnit}`;
	const rainTxt = (st: Step) => `${rainIn(st).toFixed(c.waterDigits)} ${c.waterUnit} rain`;

	const pc = (v: number | null) => (v === null ? '–' : `${Math.round(v)}%`);
	const cards = $derived.by(() => {
		if (!s) return [];
		const cum = `${(c.snow(s.cum) ?? 0).toFixed(c.snowDigits)} ${c.snowUnit} snow so far`;
		const t = c.temp(s.temp);
		return [
			{
				id: 'precip' as Metric,
				label: 'Snow and rain',
				short: 'Snow/rain',
				color: 'var(--snow)',
				value: snowIn(s) > 0.04 ? snowTxt(s) : rainy(s) ? rainTxt(s) : `0 ${c.snowUnit}`,
				sub: [
					s.kind === 'mix' && rainy(s) ? `+${rainTxt(s)}` : null,
					s.pop === null ? null : `${Math.round(s.pop)}% chance`,
					cum
				]
					.filter(Boolean)
					.join(' · ')
			},
			{
				id: 'temp' as Metric,
				label: 'Temperature',
				short: 'Temperature',
				color: 'var(--temp)',
				value: t === null ? '–' : `${Math.round(t)}${c.tempUnit}`,
				sub:
					s.tempKind === 'high'
						? 'daytime high'
						: s.tempKind === 'low'
							? 'overnight low'
							: t !== null && t <= c.freezing
								? 'below freezing'
								: 'above freezing'
			},
			{
				id: 'wind' as Metric,
				label: 'Wind',
				short: 'Wind',
				color: 'var(--wind)',
				value: `${compass(s.dir)} ${speed(s.wind, units)}`,
				sub: `gusts ${speed(s.gust, units)}`
			},
			{
				id: 'cloud' as Metric,
				label: 'Cloud cover',
				short: 'Cloud cover',
				color: 'rgb(var(--cloud))',
				value: s.cloud === null ? '–' : `${Math.round(s.cloud)}%`,
				sub: `low ${pc(s.cloudLow)} · mid ${pc(s.cloudMid)} · high ${pc(s.cloudHigh)}`
			},
			{
				id: 'fl' as Metric,
				label: 'Freezing level',
				short: 'Freezing',
				color: 'var(--level)',
				value: elevation(s.fl, units),
				sub: zone(s.fl)
			},
			{
				id: 'slr' as Metric,
				label: 'Snow ratio',
				short: 'Snow ratio',
				color: 'var(--snow)',
				value: s.kind === 'rain' ? 'Rain' : s.slr === null ? 'Too warm' : `${Math.round(s.slr)}:1`,
				sub:
					s.kind === 'rain'
						? 'too warm for snow'
						: s.slr === null
							? 'no snow at this temperature'
							: `${slrWord(s.slr)}${s.snow > 0.05 ? '' : ' (if it snows)'}`
			}
		];
	});

	const hoverY = $derived.by(() => {
		if (!s) return '0%';
		if (metric === 'precip') return toPct(yCum(c.snow(s.cum) ?? 0));
		const v = view.val(s);
		return v === null ? '-20%' : toPct(y(v));
	});

	function stepAt(e: PointerEvent): number {
		const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
		return Math.max(0, Math.min(N - 1, Math.floor(((e.clientX - r.left) / r.width) * N)));
	}
	const setHover = (k: number) => {
		const st = steps[k];
		if (st && st.t !== hoverT) hoverT = st.t;
	};
	function onkey(e: KeyboardEvent) {
		if (e.key === 'ArrowRight') setHover(Math.min(N - 1, hv + 1));
		else if (e.key === 'ArrowLeft') setHover(Math.max(0, hv - 1));
		else if (e.key === 'Enter' && s) onpick?.(s.t);
		else return;
		e.preventDefault();
	}
</script>

<div class="fc">
	<div class="top">
		<div class="titlerow">
			<h2>Forecast</h2>
			{#if place}
				<ShareButton
					label="Share this chart"
					filename={slug(`${place.name} ${METRIC_NAME[metric]} ${R} day`)}
					render={(shape) =>
						paint(shape, (ctx, p) =>
							drawForecastCard(ctx, shape, { ...place, band, bands, units, metric, range: R }, p)
						)}
				/>
			{/if}
		</div>
		<div class="seg" role="group" aria-label="Time range">
			{#each ranges as r (r)}
				<button aria-pressed={R === r} onclick={() => (range = r)}
					>{r} {r === 1 ? 'day' : 'days'}</button
				>
			{/each}
		</div>
	</div>
	<div class="readout">
		<span class="faint"
			>{resolution[STEP[R]]} · hover or use the arrow keys to read each period</span
		>
		{#if s}<strong>{when(s)}</strong>{/if}
	</div>

	<div class="cards" role="tablist" aria-label="Chart metric">
		{#each cards as k (k.id)}
			<button
				role="tab"
				class="mcard"
				class:on={metric === k.id}
				aria-selected={metric === k.id}
				onclick={() => (metric = k.id)}
			>
				<span class="mlabel"
					><i style:background={k.color}></i><span class="mtxt long">{k.label}</span><span
						class="mtxt short">{k.short}</span
					></span
				>
				<span class="mval num">{k.value}</span>
				<span class="msub">{k.sub}</span>
			</button>
		{/each}
	</div>

	<div class="axes">
		<span>{axisTitle}</span>
		{#if metric === 'precip'}<span>Snow total ({c.snowUnit})</span>{/if}
	</div>
	<div class="plotrow">
		<div class="yaxis left">
			{#each yticks as t (t.label + t.y)}<span class={t.cls} style:top={toPct(t.y)}
					>{t.label}{#if t.sub}<small>{t.sub}</small>{/if}</span
				>{/each}
		</div>
		<div
			class="plot"
			bind:clientHeight={plotH}
			bind:clientWidth={plotW}
			role="slider"
			tabindex="0"
			aria-label="Forecast chart: {axisTitle}"
			aria-valuemin={0}
			aria-valuemax={N - 1}
			aria-valuenow={hv}
			aria-valuetext={s ? `${when(s)}: ${cards.find((k) => k.id === metric)?.value ?? ''}` : ''}
			onpointermove={(e) => setHover(stepAt(e))}
			onpointerdown={(e) => setHover(stepAt(e))}
			onclick={() => s && onpick?.(s.t)}
			onkeydown={onkey}
		>
			<svg viewBox="0 0 1000 300" preserveAspectRatio="none" aria-hidden="true">
				<path d={shade} class="night" />
				{#each paths.zones as z (z.cls)}<rect
						x="0"
						y={z.y}
						width="1000"
						height={z.h}
						class="zone {z.cls}"
					/>{/each}
				<path d={grid} class="grid" class:lanegrid={metric === 'cloud'} />
				<path d={midnights} class="midnight" />
				{#each paths.clouds as d, i (i)}<path {d} class="cloudband" />{/each}
				<path d={paths.bars.snow} class="b-snow" />
				<path d={paths.bars.heavy} class="b-heavy" />
				<path d={paths.bars.mix} class="b-mix" />
				<path d={paths.bars.rain} class="b-rain" />
				<path d={paths.faint} class="line faint m-{metric}" />
				<path d={paths.band} class="band b-{metric}" />
				<path d={paths.line2} class="line2 m-{metric}" />
				<path d={paths.line} class="line m-{metric}" />
			</svg>
			{#each rainMarks as m (m.left)}<span class="rainlbl" style:left={m.left} style:top={m.top}
					>{m.label}</span
				>{/each}
			{#if metric === 'slr'}
				{#each ZONES as z (z.cls)}<span
						class="zonename {z.cls}"
						style:top={toPct((y(z.hi) + y(z.lo)) / 2)}>{z.name}</span
					>{/each}
			{/if}
			{#if conf}
				<div class="conf" style:left={conf.left}>
					{#if conf.roomy}<span>Less certain →</span>{/if}
				</div>
			{/if}
			{#each refs as r (r.key)}
				<div class="ref" style:top={r.top}></div>
				<span class="reflbl" style:top={r.labelTop} style:left={r.labelLeft}
					>{r.name}{#if r.elev}<b class="num">{r.elev}</b>{/if}</span
				>
			{/each}
			{#if s}
				<div class="cursor" style:left="{((hv + 0.5) / N) * 100}%"></div>
				{#if metric !== 'cloud'}
					<div
						class="dot m-{metric}"
						style:left="{((hv + 0.5) / N) * 100}%"
						style:top={hoverY}
					></div>
				{/if}
			{/if}
		</div>
		<div class="yaxis right">
			{#if metric === 'precip'}
				{#each cumAxis.ticks as v (v)}<span style:top={toPct(yCum(v))}>{v}</span>{/each}
			{/if}
		</div>
	</div>
	<div class="lower" aria-hidden="true">
		<div class="yaxis left lowaxis">
			{#each [0, 50, 100] as v (v)}<span style:top="{100 - v}%">{v}%</span>{/each}
		</div>
		<div class="lplot">
			<svg viewBox="0 0 1000 100" preserveAspectRatio="none">
				<path d={lower.shade} class="night" />
				<path d="M0 50H1000M0 0H1000" class="grid" />
				<path d={lower.cloud} class="cloudarea" />
				<path d={lower.pop} class="popbars" />
			</svg>
			{#if s}<div class="cursor" style:left="{((hv + 0.5) / N) * 100}%"></div>{/if}
		</div>
		<div class="yaxis right lowaxis"></div>
	</div>
	<div class="xaxis">
		{#each xlabels as x (x.left)}
			<span style:left={x.left} class:strong={x.strong} class:minor={x.minor}
				>{x.name}<small>{x.sub}</small></span
			>
		{/each}
	</div>
	<div class="legend">
		<span><i class="sw night"></i>Night (shaded)</span>
		{#if metric === 'precip'}
			<span><i class="sw" style:background="var(--snow)"></i>Snow</span>
			<span
				><i class="sw" style:background="var(--snow-heavy)"></i>Heavy: {c.snowUnit === 'in'
					? '6+ in'
					: '15+ cm'} in one bar</span
			>
			<span><i class="sw" style:background="var(--mix)"></i>Mixed (snow part)</span>
			<span
				><i class="sw" style:background="var(--rain)"></i>All rain: marks along the bottom, labelled
				in
				{units === 'imperial' ? 'inches' : 'mm'} of water (not on the snow scale)</span
			>
			<span>Line: running snow total, right axis</span>
		{:else if metric === 'slr'}
			<span><i class="sw z-dry-sw"></i>Dry powder</span>
			<span><i class="sw z-light-sw"></i>Light</span>
			<span><i class="sw z-avg-sw"></i>Average</span>
			<span><i class="sw z-wet-sw"></i>Heavy & wet</span>
			<span>Solid line while snow falls; faint when dry (the ratio if it snowed)</span>
			<span><i class="sw" style:background="var(--rain)"></i>Too warm: rain marks</span>
		{:else if metric === 'temp'}
			<span
				>{STEP[R] === 12 ? 'Days show the high, nights the low · ' : ''}Dashed line: freezing</span
			>
		{:else if metric === 'wind'}
			<span>Solid: strongest sustained wind · Dashed: peak gust</span>
		{:else if metric === 'cloud'}
			<span>The thicker the band, the more of the sky is covered at that height</span>
		{:else}
			<span>Dashed lines: this location's elevations</span>
		{/if}
		{#if metric === 'temp' || metric === 'fl'}<span
				><i class="sw band-sw b-{metric}"></i>Range across the weather models</span
			>{/if}
		<span class="lower-key"
			><i class="sw cloud-sw"></i>Cloud cover <i class="sw pop-sw"></i>Chance of precipitation
			(lower panel)</span
		>
	</div>
</div>

<style>
	.fc {
		display: grid;
		gap: 14px;
		min-width: 0;
	}
	.top {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}
	.titlerow {
		flex: 1 1 auto;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
	}
	h2 {
		margin: 0;
		font-family: var(--font-num);
		font-size: 1.2rem;
		font-weight: 600;
	}
	.readout {
		height: 20px;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
		font-size: 0.82rem;
		white-space: nowrap;
		overflow: hidden;
	}
	.readout span {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.readout strong {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	/* Metric cards: every card visible at once (6 across on desktop, 3 + 3 below), fixed
	   heights so the values never reflow while you scrub the chart. */
	.cards {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 8px;
	}
	@media (min-width: 1100px) {
		.cards {
			grid-template-columns: repeat(6, minmax(0, 1fr));
		}
	}
	.mcard {
		min-width: 0;
		height: 100px;
		box-sizing: border-box;
		overflow: hidden;
		text-align: left;
		display: flex;
		flex-direction: column;
		justify-content: flex-start;
		gap: 4px;
		padding: 10px 12px;
		border-radius: 14px;
		border: 1px solid var(--border);
		background: var(--surface);
		cursor: pointer;
	}
	.mcard.on {
		border-color: var(--accent);
		background: var(--accent-soft);
	}
	.mlabel {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--text-2);
		white-space: nowrap;
	}
	.mtxt {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.mtxt.short {
		display: none;
	}
	.mlabel i {
		width: 10px;
		height: 10px;
		border-radius: 3px;
		flex-shrink: 0;
	}
	.mval {
		font-size: 1.3rem;
		font-weight: 600;
		line-height: 1.1;
		white-space: nowrap;
	}
	.msub {
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		font-size: 0.75rem;
		line-height: 1.25;
		color: var(--text-3);
		overflow: hidden;
	}
	.axes {
		display: flex;
		justify-content: space-between;
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--text-2);
		white-space: nowrap;
		margin-bottom: -6px;
	}
	.plotrow {
		display: flex;
		gap: 8px;
	}
	.yaxis {
		position: relative;
		width: 46px;
		height: 280px;
		flex-shrink: 0;
		font-size: 0.72rem;
		color: var(--text-3);
		font-variant-numeric: tabular-nums;
	}
	.yaxis span {
		position: absolute;
		transform: translateY(-50%);
		white-space: nowrap;
	}
	.yaxis.left span {
		right: 0;
		text-align: right;
	}
	.yaxis.right {
		width: 34px;
	}
	.plot {
		position: relative;
		flex: 1;
		min-width: 0;
		height: 280px;
		border-bottom: 1px solid var(--border);
		cursor: crosshair;
		touch-action: pan-y;
		/* Keep labels and the hover dot inside the plot so the page never scrolls sideways. */
		overflow: clip;
		overflow-clip-margin: 8px;
	}
	.plot svg {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		display: block;
	}
	.plot path {
		vector-effect: non-scaling-stroke;
	}
	.night {
		fill: var(--night);
	}
	.grid {
		fill: none;
		stroke: var(--grid);
	}
	.midnight {
		fill: none;
		stroke: var(--border);
	}
	.b-snow {
		fill: var(--snow);
	}
	.b-heavy {
		fill: var(--snow-heavy);
	}
	.b-mix {
		fill: var(--mix);
	}
	.b-rain {
		fill: var(--rain);
	}
	.rainlbl {
		position: absolute;
		transform: translate(-50%, calc(-100% - 2px));
		font-size: 0.66rem;
		font-weight: 600;
		color: var(--rain);
		pointer-events: none;
		white-space: nowrap;
	}
	/* Snow ratio zones: deeper blue for drier snow. */
	.zone {
		stroke: none;
	}
	.z-wet {
		fill: color-mix(in srgb, var(--mix) 12%, transparent);
	}
	.z-avg {
		fill: color-mix(in srgb, var(--snow) 8%, transparent);
	}
	.z-light {
		fill: color-mix(in srgb, var(--snow) 16%, transparent);
	}
	.z-dry {
		fill: color-mix(in srgb, var(--snow) 26%, transparent);
	}
	.z-wet-sw {
		background: color-mix(in srgb, var(--mix) 30%, var(--surface));
	}
	.z-avg-sw {
		background: color-mix(in srgb, var(--snow) 22%, var(--surface));
	}
	.z-light-sw {
		background: color-mix(in srgb, var(--snow) 40%, var(--surface));
	}
	.z-dry-sw {
		background: color-mix(in srgb, var(--snow) 62%, var(--surface));
	}
	.zonename {
		position: absolute;
		right: 8px;
		transform: translateY(-50%);
		font-size: 0.68rem;
		font-weight: 600;
		color: var(--text-2);
		pointer-events: none;
	}
	.m-slr {
		stroke: var(--snow);
	}
	.line.faint {
		stroke-width: 1.5;
		stroke-dasharray: 3 4;
		opacity: 0.6;
	}
	.dot.m-slr {
		border-color: var(--snow);
	}
	@media (max-width: 899px) {
		.rainlbl {
			display: none;
		}
	}
	.line,
	.line2 {
		fill: none;
		stroke-width: 2.5;
		stroke-linejoin: round;
	}
	.line2 {
		stroke-width: 2;
		stroke-dasharray: 6 5;
	}
	/* Model spread: soft, no outline. */
	.band {
		stroke: none;
		fill-opacity: 0.1;
	}
	.band.b-temp {
		fill: var(--temp);
	}
	.band.b-fl {
		fill: var(--level);
	}
	.band-sw.b-temp {
		background: color-mix(in srgb, var(--temp) 16%, transparent);
	}
	.band-sw.b-fl {
		background: color-mix(in srgb, var(--level) 16%, transparent);
	}
	.yaxis span small {
		display: block;
		font-size: 0.62rem;
		font-weight: 400;
		color: var(--text-3);
	}
	.cloudband {
		fill: rgb(var(--cloud) / 0.75);
		stroke: rgb(var(--cloud));
		stroke-width: 1;
	}
	.grid.lanegrid {
		stroke-dasharray: 3 4;
	}
	.popbars {
		fill: var(--text-2);
		fill-opacity: 0.75;
	}
	.pop-sw {
		width: 4px;
		height: 12px;
		background: var(--text-2);
		margin-left: 10px;
	}
	/* Lower panel: cloud cover and chance of precipitation; wide screens only. */
	.lower {
		display: flex;
		gap: 8px;
		margin-top: -2px;
	}
	.yaxis.lowaxis {
		height: 84px;
	}
	.lplot {
		position: relative;
		flex: 1;
		min-width: 0;
		height: 84px;
		border-bottom: 1px solid var(--border);
		overflow: clip;
	}
	.lplot svg {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
	}
	.lplot path {
		vector-effect: non-scaling-stroke;
	}
	.yaxis span.lane {
		font-weight: 600;
		color: var(--text-2);
	}
	.cloudarea {
		fill: rgb(var(--cloud) / 0.22);
		stroke: none;
	}
	.cloud-sw {
		background: rgb(var(--cloud) / 0.3);
	}
	.area {
		fill-opacity: 0.18;
		stroke: none;
	}
	.m-precip {
		stroke: var(--text);
	}
	.m-temp {
		stroke: var(--temp);
	}
	.m-wind {
		stroke: var(--wind);
	}
	.m-cloud {
		stroke: rgb(var(--cloud));
		fill: rgb(var(--cloud));
	}
	.line.m-cloud,
	.line2.m-cloud {
		fill: none;
	}
	.m-fl {
		stroke: var(--level);
	}
	.conf {
		position: absolute;
		top: 0;
		bottom: 0;
		right: 0;
		background: color-mix(in srgb, var(--surface) 45%, transparent);
		border-left: 1px dashed var(--text-3);
		pointer-events: none;
	}
	.conf span {
		position: absolute;
		top: 6px;
		left: 8px;
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--text-2);
		white-space: nowrap;
	}
	/* Quiet guide lines, so the data line stays the thing you read. */
	.ref {
		position: absolute;
		left: 0;
		right: 0;
		border-top: 1px dashed color-mix(in srgb, var(--text-2) 55%, transparent);
		pointer-events: none;
	}
	.reflbl {
		position: absolute;
		height: 15px;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 0 5px;
		border-radius: 5px;
		font-size: 10px;
		font-weight: 500;
		line-height: 1;
		color: var(--text-2);
		background: color-mix(in srgb, var(--surface) 88%, transparent);
		white-space: nowrap;
		pointer-events: none;
	}
	.reflbl b {
		font-weight: 600;
		color: var(--text);
	}
	.cursor {
		position: absolute;
		top: 0;
		bottom: 0;
		border-left: 1.5px solid var(--text);
		pointer-events: none;
	}
	.dot {
		position: absolute;
		width: 12px;
		height: 12px;
		margin: -6px 0 0 -6px;
		border-radius: 50%;
		background: var(--surface);
		border: 3px solid;
		border-color: var(--text);
		pointer-events: none;
	}
	.dot.m-temp {
		border-color: var(--temp);
	}
	.dot.m-wind {
		border-color: var(--wind);
	}
	.dot.m-cloud {
		border-color: rgb(var(--cloud));
		background: var(--surface);
	}
	.dot.m-fl {
		border-color: var(--level);
	}
	.xaxis {
		position: relative;
		height: 32px;
		margin: -6px 42px 0 54px;
	}
	.xaxis span {
		position: absolute;
		transform: translateX(-50%);
		display: grid;
		justify-items: center;
		font-size: 0.72rem;
		color: var(--text-3);
		white-space: nowrap;
	}
	.xaxis span.strong {
		font-weight: 600;
		color: var(--text);
	}
	.xaxis small {
		font-size: 0.68rem;
		font-weight: 400;
		color: var(--text-3);
	}
	.legend {
		min-height: 18px;
		display: flex;
		flex-wrap: wrap;
		gap: 6px 16px;
		font-size: 0.75rem;
		color: var(--text-3);
	}
	.legend span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.sw {
		width: 10px;
		height: 10px;
		border-radius: 2px;
	}
	.sw.night {
		width: 14px;
		background: var(--night);
		border: 1px solid var(--border);
	}
	@media (max-width: 899px) {
		.lower,
		.legend .lower-key {
			display: none;
		}
	}
	@media (max-width: 640px) {
		.cards {
			gap: 6px;
		}
		.mcard {
			height: 58px;
			padding: 8px 9px;
			gap: 3px;
			border-radius: 12px;
		}
		.mlabel {
			gap: 5px;
			font-size: 0.7rem;
		}
		.mlabel i {
			width: 8px;
			height: 8px;
			border-radius: 2px;
		}
		.mval {
			font-size: 1.05rem;
		}
		.mtxt.long {
			display: none;
		}
		.mtxt.short {
			display: inline;
		}
		/* Too narrow for the detail line; the period sheet has it. */
		.msub {
			display: none;
		}
		.yaxis,
		.plot {
			height: 220px;
		}
		.yaxis {
			width: 38px;
		}
		.yaxis.right {
			width: 24px;
		}
		.xaxis {
			margin: -6px 32px 0 46px;
		}
		.readout span {
			display: none;
		}
		.xaxis span.minor {
			display: none;
		}
	}
</style>
