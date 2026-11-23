<!-- Compare: the chosen locations on one chart. One solid line per location, in its own
     colour (cloud cover is a lane per location instead, since cloud jumps 0–100 % and
     its lines would tangle). The readout sits above the plot, where a finger scrubbing
     the plot doesn't cover it, and always keeps room for four rows so nothing moves.
     On the freezing-level view, a tick on the right edge marks each location's elevation. -->
<script lang="ts">
	import {
		fzSide,
		LIFT_HOLD_KMH,
		METRICS,
		METRIC_NAMES,
		stepValue,
		windowTotals,
		maxWindowTotal,
		MAX_LINES,
		type CompareMetric,
		type Comparison,
		type Timeline,
		type Track,
		type Win
	} from '../compare';
	import { niceAxis, STEP, type Step } from './forecast';
	import { converters, elevation, speed, type UnitSystem } from '../units';
	import { compass } from '../conditions';
	import { dateOf, hourLabel, hourOf, monthDay, weekday } from '../time';
	import { viewport } from '../viewport.svelte';
	import { scrubLock } from './scrub';

	interface Props {
		timeline: Timeline;
		cmp: Comparison;
		units: UnitSystem;
		/** The slots in view. */
		win: Win;
		/** The time being read (bindable, so it survives a change of metric or range). */
		hoverT?: string | null;
		onmetric: (m: CompareMetric) => void;
		/** Shown in the plot when no line is drawn. */
		empty?: string;
		/** The location being pointed at (here or in its row): its line stands out. */
		hl?: string | null;
	}

	let {
		timeline,
		cmp,
		units,
		win,
		hoverT = $bindable(null),
		onmetric,
		empty = 'Tap a location’s name below to draw its line.',
		hl = $bindable(null)
	}: Props = $props();

	const phone = $derived(viewport.phone);
	const c = $derived(converters(units));
	const metric = $derived(cmp.metric);
	const R = $derived(cmp.range);
	const H = 300;
	const refT = $derived(timeline.ref?.band.hourly.t ?? []);

	const steps = $derived(timeline.slots.slice(win.off, win.off + win.n));
	const N = $derived(Math.max(1, steps.length));
	const W = $derived(1000 / N);

	/** The charted locations: each line colour that holds a loaded location. */
	const lines = $derived(
		cmp.on.flatMap((id, slot) => {
			const track = id ? timeline.tracks.find((t) => t.id === id) : undefined;
			return track ? [{ slot, track }] : [];
		})
	);

	/** A metric value in display units. */
	const shown = (v: number | null): number | null => {
		if (v === null) return null;
		if (metric === 'snow') return c.snow(v);
		if (metric === 'temp') return c.temp(v);
		if (metric === 'wind') return c.speed(v);
		if (metric === 'fl') return c.height(v);
		return v;
	};
	/** Each charted location's values across the window, in display units. Snow is a
	 *  running total from the window's first step, so a line ends at its row's total. */
	const series = $derived(
		new Map(
			lines.map(({ track }) => {
				const inView = track.steps.slice(win.off, win.off + win.n);
				const vals =
					metric === 'snow'
						? windowTotals(inView).map((v) => shown(v))
						: inView.map((st) => shown(stepValue(st, metric)));
				return [track.id, vals] as const;
			})
		)
	);
	/** A track's value at step `k` of the window. */
	const valIn = (t: Track, k: number) => series.get(t.id)?.[k] ?? null;

	// One scale for the whole forecast (not just the window), so lines keep their heights
	// as the window moves: snow to the snowiest window anywhere, the rest to every value.
	const axis = $derived.by(() => {
		if (metric === 'snow') {
			const most = lines.map((l) => c.snow(maxWindowTotal(l.track.steps, win.n)) ?? 0);
			return niceAxis(0, Math.max(units === 'imperial' ? 1 : 2, ...most), 4);
		}
		const vals = lines
			.flatMap(({ track }) => track.steps.map((st) => shown(stepValue(st, metric))))
			.filter((v): v is number => v !== null);
		if (metric === 'temp')
			return niceAxis(Math.min(c.freezing, ...vals) - 2, Math.max(c.freezing, ...vals) + 2, 4);
		if (metric === 'wind') return niceAxis(0, Math.max(10, ...vals), 4);
		if (metric === 'fl') {
			const all = [...vals, ...lines.map((l) => c.height(l.track.band.elev_m) ?? 0)];
			if (!all.length) return niceAxis(0, units === 'imperial' ? 10000 : 3000, 4);
			return niceAxis(Math.min(...all) * 0.9, Math.max(...all) * 1.05, 4);
		}
		if (metric === 'slr') return { min: 4, max: 20, ticks: [5, 8, 11, 14, 17, 20] };
		return { min: 0, max: 100, ticks: [0, 25, 50, 75, 100] };
	});
	const y = (v: number) =>
		Math.min(H, Math.max(0, H - ((v - axis.min) / (axis.max - axis.min)) * H));
	const pct = (yy: number) => `${((yy / H) * 100).toFixed(2)}%`;
	const xAt = (k: number) => k * W + W / 2;

	const paths = $derived(
		metric === 'cloud'
			? []
			: lines.map(({ slot, track }) => {
					let d = '';
					let pen = false;
					for (let k = 0; k < N; k++) {
						const v = valIn(track, k);
						if (v === null) {
							pen = false;
							continue;
						}
						d += `${pen ? 'L' : 'M'}${xAt(k).toFixed(1)} ${y(v).toFixed(1)}`;
						pen = true;
					}
					return { slot, id: track.id, d };
				})
	);

	// Cloud: a lane per location, darker for more of the sky covered.
	const lanes = $derived(
		metric !== 'cloud'
			? []
			: lines.map(({ slot, track }, i) => {
					const lh = H / lines.length;
					const cells: { x: number; op: number }[] = [];
					for (let k = 0; k < N; k++) {
						const v = stepValue(track.steps[win.off + k], 'cloud');
						if (v !== null) cells.push({ x: k * W, op: 0.06 + (0.84 * v) / 100 });
					}
					return { slot, id: track.id, name: track.name, y0: i * lh, h: lh, cells };
				})
	);

	// Night shading helps on the 1 and 3 day views, where steps are hours.
	const showNight = $derived(STEP[R] < 6);
	const shade = $derived(
		showNight
			? steps
					.map((st, k) =>
						st.night ? `M${(k * W).toFixed(2)} 0h${W.toFixed(2)}v${H}h-${W.toFixed(2)}z` : ''
					)
					.join('')
			: ''
	);

	const ticks = $derived(metric === 'cloud' ? [] : axis.ticks);
	const tickLabel = (v: number) => {
		if (metric === 'temp') return `${v}°`;
		if (metric === 'slr') return `${v}:1`;
		if (metric === 'fl')
			return units === 'imperial'
				? `${(v / 1000).toLocaleString('en-US')}k ft`
				: `${v.toLocaleString('en-US')} m`;
		return `${v}`;
	};
	const grid = $derived(ticks.map((v) => `M0 ${y(v).toFixed(1)}H1000`).join(''));

	// Days and hours along the bottom, from the reference location's clock.
	const span = $derived(N * STEP[R]);
	const i0 = $derived(steps[0]?.i0 ?? 0);
	const pos = (i: number) => (i - i0) / span;
	const dayEdges = $derived.by(() => {
		const out: number[] = [];
		for (let i = i0 + 1; i < i0 + span; i++) if (refT[i] && hourOf(refT[i]) === 0) out.push(pos(i));
		return out;
	});
	const midnights = $derived(dayEdges.map((f) => `M${(f * 1000).toFixed(1)} 0V${H}`).join(''));
	const clock = (hr: number) =>
		hr === 0 ? '12 AM' : hr < 12 ? `${hr} AM` : hr === 12 ? 'Noon' : `${hr - 12} PM`;
	const xlabels = $derived.by(() => {
		const out: { left: string; name: string; sub: string; strong: boolean }[] = [];
		const at = (i: number) => `${(pos(i) * 100).toFixed(2)}%`;
		for (let i = i0; i < i0 + span && i < refT.length; i++) {
			const hr = hourOf(refT[i]);
			const d = dateOf(refT[i]);
			if (R === 1) {
				if (i > i0 && hr % 6 === 0)
					out.push({ left: at(i), name: clock(hr), sub: '', strong: false });
			} else if (R === 3) {
				if (hr === 0 && i > i0)
					out.push({ left: at(i), name: weekday(d), sub: monthDay(d), strong: true });
				else if (hr === 12 && !phone)
					out.push({ left: at(i), name: 'Noon', sub: '', strong: false });
			} else if (hr === 12) {
				out.push({
					left: at(i),
					// Ten days on a phone leave about 27 px a day: two letters fit.
					name: R >= 10 && phone ? weekday(d).slice(0, 2) : weekday(d),
					sub: R >= 10 ? String(Number(d.slice(8))) : monthDay(d),
					strong: true
				});
			}
		}
		return out;
	});

	// The step being read: the pointer's, or the window's end for snow (the totals) and its
	// start (now) for the rest.
	const hv = $derived.by(() => {
		if (!steps.length) return 0;
		const t = hoverT ? Date.parse(hoverT) : NaN;
		if (Number.isNaN(t)) return metric === 'snow' ? steps.length - 1 : 0;
		let k = steps.findIndex((s) => Date.parse(s.t) > t) - 1;
		if (k < 0) k = Date.parse(steps[0].t) > t ? 0 : steps.length - 1;
		return k;
	});
	const when = $derived.by(() => {
		const st = steps[hv];
		if (!st) return '';
		const d = `${weekday(dateOf(st.t))} ${monthDay(dateOf(st.t))}`;
		if (st.hours === 1) return `${d} · ${hourLabel(st.t)}`;
		if (st.hours === 12) return `${d} · ${st.night ? 'night, 6 PM–6 AM' : 'day, 6 AM–6 PM'}`;
		const end = refT[st.i0 + st.hours];
		return `${d} · ${hourLabel(st.t)}–${end ? hourLabel(end) : ''}`;
	});

	const FZ_WORDS = {
		snow: 'cold enough to snow',
		wet: 'near the snow line',
		warm: 'too warm to snow'
	};
	const SLR_WORD = (v: number) =>
		v < 9.5 ? 'heavy & wet' : v < 12.5 ? 'average' : v < 15.5 ? 'light' : 'dry powder';
	function reading(
		st: Step | null | undefined,
		t: Track,
		k: number
	): { value: string; detail: string } {
		if (!st) return { value: '–', detail: 'no forecast here' };
		if (metric === 'snow') {
			const cum = valIn(t, k) ?? 0;
			const now = c.snow(st.snow) ?? 0;
			const digits = STEP[R] <= 3 ? c.snowDigits + 1 : c.snowDigits;
			return {
				value: `${cum.toFixed(c.snowDigits)} ${c.snowUnit}`,
				detail:
					now >= 0.5 * 10 ** -digits
						? `+${now.toFixed(digits)} this step`
						: st.kind === 'rain'
							? 'rain'
							: ''
			};
		}
		if (metric === 'temp') {
			const v = c.temp(st.temp);
			return {
				value: v === null ? '–' : `${Math.round(v)}${c.tempUnit}`,
				detail: st.tempKind === 'high' ? 'high' : st.tempKind === 'low' ? 'low' : ''
			};
		}
		if (metric === 'wind')
			return {
				value: speed(st.gust, units),
				detail: st.wind === null ? '' : `wind ${compass(st.dir)} ${speed(st.wind, units)}`
			};
		if (metric === 'cloud')
			return { value: st.cloud === null ? '–' : `${Math.round(st.cloud)}%`, detail: '' };
		if (metric === 'fl') {
			const fz = fzSide(st.fl, t.band.elev_m);
			return {
				value: elevation(st.fl, units),
				detail: fz
					? `${elevation(Math.abs(fz.diff), units)} ${fz.diff <= 0 ? 'below' : 'above'}${phone ? '' : ` · ${FZ_WORDS[fz.word]}`}`
					: ''
			};
		}
		if (st.kind === 'rain') return { value: 'Rain', detail: 'too warm for snow' };
		if (st.slr === null) return { value: '–', detail: 'too warm for snow' };
		return {
			value: `${Math.round(st.slr)}:1`,
			detail: `${SLR_WORD(st.slr)}${st.snow > 0.05 ? '' : ' if it snows'}`
		};
	}
	const reads = $derived(
		lines.map(({ slot, track }) => ({
			slot,
			id: track.id,
			name: track.name,
			where: `${track.band.label} · ${elevation(track.band.elev_m, units)}`,
			...reading(track.steps[win.off + hv], track, hv)
		}))
	);
	/** Room for four rows, always: placeholders after the charted ones. */
	const spare = $derived(Math.max(0, MAX_LINES - reads.length));

	// Reference lines: freezing on the temperature view, the lift-hold gust on wind.
	const refs = $derived.by(() => {
		if (metric === 'temp') return [{ key: 'frz', y: y(c.freezing), label: `${c.freezing}°` }];
		if (metric === 'wind') {
			const hold = c.speed(LIFT_HOLD_KMH) ?? 0;
			return hold <= axis.max ? [{ key: 'hold', y: y(hold), label: 'Lift holds likely' }] : [];
		}
		return [];
	});
	const flTicks = $derived(
		metric === 'fl'
			? lines.map(({ slot, track }) => ({
					slot,
					id: track.id,
					top: pct(y(c.height(track.band.elev_m) ?? 0)),
					title: `${track.name}: ${track.band.label}, ${elevation(track.band.elev_m, units)}`
				}))
			: []
	);
	const ZONES = [
		{ lo: 4, hi: 9.5, name: 'Heavy & wet', cls: 'z-wet' },
		{ lo: 9.5, hi: 12.5, name: 'Average', cls: 'z-avg' },
		{ lo: 12.5, hi: 15.5, name: 'Light', cls: 'z-light' },
		{ lo: 15.5, hi: 20, name: 'Dry powder', cls: 'z-dry' }
	];

	const dots = $derived(
		metric === 'cloud'
			? []
			: lines.flatMap(({ slot, track }) => {
					const v = valIn(track, hv);
					return v === null ? [] : [{ slot, id: track.id, top: pct(y(v)) }];
				})
	);

	const axisTitle = $derived(
		{
			snow: `Snow from ${win.off === 0 || !steps[0] ? 'now' : `${weekday(dateOf(steps[0].t))} ${hourLabel(steps[0].t)}`} (${c.snowUnit})`,
			temp: `Temperature (${c.tempUnit})`,
			wind: `Wind gusts (${c.speedUnit})`,
			cloud: 'Cloud cover: darker is more of the sky covered',
			fl: `Freezing level (${c.heightUnit}); a tick marks each location’s elevation`,
			slr: 'Snow ratio (inches of snow from an inch of water)'
		}[metric]
	);

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
		else return;
		e.preventDefault();
	}
	/** Pointing with a mouse marks a location; touch has no hover, so it doesn't. */
	const mark = (e: PointerEvent, id: string | null) => {
		if (e.pointerType === 'mouse') hl = id;
	};
	const valueText = $derived(
		reads.length ? `${when}: ${reads.map((r) => `${r.name} ${r.value}`).join(', ')}` : empty
	);
</script>

<div class="cc" class:phone>
	<div class="metrics" role="group" aria-label="Chart metric">
		{#each METRICS as m (m)}
			<button aria-pressed={metric === m} onclick={() => onmetric(m)}
				>{phone ? METRIC_NAMES[m].short : METRIC_NAMES[m].long}</button
			>
		{/each}
	</div>

	<div class="readout">
		<div class="when">{reads.length ? when : ''}</div>
		<div class="reads">
			{#each reads as r (r.id)}
				<div
					class="read s{r.slot}"
					class:hl={hl === r.id}
					role="group"
					aria-label={r.name}
					onpointerenter={(e) => mark(e, r.id)}
					onpointerleave={(e) => mark(e, null)}
				>
					<span class="who"><i class="key s{r.slot}"></i><span class="rname">{r.name}</span></span>
					<span class="rv"
						><strong class="rval num">{r.value}</strong><span class="rdet">{r.detail}</span></span
					>
					{#if !phone}<span class="where">{r.where}</span>{/if}
				</div>
			{/each}
			{#each { length: spare }, i (i)}<div class="read spare" aria-hidden="true"></div>{/each}
		</div>
	</div>

	<div class="axes">{axisTitle}</div>
	<div class="plotrow">
		<div class="yaxis">
			{#each ticks as v (v)}<span style:top={pct(y(v))}>{tickLabel(v)}</span>{/each}
		</div>
		<div
			class="plot"
			role="slider"
			tabindex="0"
			aria-label="Compare chart: {axisTitle}"
			aria-valuemin={0}
			aria-valuemax={N - 1}
			aria-valuenow={hv}
			aria-valuetext={valueText}
			onpointermove={(e) => setHover(stepAt(e))}
			onpointerdown={(e) => setHover(stepAt(e))}
			onkeydown={onkey}
			use:scrubLock
		>
			<svg viewBox="0 0 1000 300" preserveAspectRatio="none" aria-hidden="true">
				<path d={shade} class="night" />
				{#if metric === 'slr'}
					{#each ZONES as z (z.cls)}<rect
							x="0"
							y={y(z.hi)}
							width="1000"
							height={y(z.lo) - y(z.hi)}
							class="zone {z.cls}"
						/>{/each}
				{/if}
				<path d={grid} class="grid" />
				<path d={midnights} class="grid" />
				{#each lanes as l (l.id)}
					{#each l.cells as cell (cell.x)}<rect
							x={cell.x}
							y={l.y0 + 3}
							width={W}
							height={Math.max(0, l.h - 6)}
							class="cloud"
							fill-opacity={cell.op.toFixed(3)}
						/>{/each}
				{/each}
				{#each paths as p (p.id)}<path
						d={p.d}
						class="line s{p.slot}"
						class:faded={hl !== null && hl !== p.id}
						class:hl={hl === p.id}
					/>{/each}
			</svg>
			{#if metric === 'slr'}
				{#each ZONES as z (z.cls)}<span class="zonename" style:top={pct((y(z.hi) + y(z.lo)) / 2)}
						>{z.name}</span
					>{/each}
			{/if}
			{#each lanes as l (l.id)}
				<span class="lanename" style:top={pct(l.y0 + 6)}><i class="key s{l.slot}"></i>{l.name}</span
				>
			{/each}
			{#each refs as r (r.key)}
				<div class="ref" style:top={pct(r.y)}></div>
				<span class="reflbl" style:top={pct(r.y)}>{r.label}</span>
			{/each}
			{#each flTicks as f (f.id)}<span class="fltick s{f.slot}" style:top={f.top} title={f.title}
				></span>{/each}
			{#if !lines.length}<p class="none">{empty}</p>{/if}
			{#if lines.length && steps.length}
				<div class="cursor" style:left="{((hv + 0.5) / N) * 100}%"></div>
				{#each dots as d (d.id)}<div
						class="dot s{d.slot}"
						class:faded={hl !== null && hl !== d.id}
						style:left="{((hv + 0.5) / N) * 100}%"
						style:top={d.top}
					></div>{/each}
			{/if}
		</div>
	</div>
	<div class="xaxis" aria-hidden="true">
		<div class="yspace"></div>
		<div class="xticks">
			{#each xlabels as x (x.left)}<span style:left={x.left} class:strong={x.strong}
					>{x.name}{#if x.sub}<small>{x.sub}</small>{/if}</span
				>{/each}
		</div>
	</div>
</div>

<style>
	.cc {
		display: grid;
		gap: 12px;
		min-width: 0;
		--plot-h: 280px;
	}
	.cc.phone {
		gap: 8px;
		--plot-h: 210px;
	}
	/* The six metrics: a well with the chosen one raised (3 + 3 on phones). */
	.metrics {
		display: grid;
		grid-template-columns: repeat(6, minmax(0, 1fr));
		gap: 2px;
		padding: 3px;
		border-radius: 18px;
		background: var(--surface-2);
	}
	.phone .metrics {
		grid-template-columns: repeat(3, minmax(0, 1fr));
	}
	.metrics button {
		min-width: 0;
		min-height: 36px;
		border: 0;
		border-radius: 14px;
		background: transparent;
		color: var(--text-2);
		font-size: 0.86rem;
		font-weight: 500;
		cursor: pointer;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		transition:
			background-color var(--ease),
			box-shadow var(--ease),
			color var(--ease);
	}
	.metrics button:hover {
		color: var(--text);
	}
	.metrics button[aria-pressed='true'] {
		background: var(--sel);
		color: var(--text);
		box-shadow: var(--sel-shadow);
	}

	/* Line colours, one per slot: identity, never a metric. */
	.s0 {
		--k: var(--cmp1);
	}
	.s1 {
		--k: var(--cmp2);
	}
	.s2 {
		--k: var(--cmp3);
	}
	.s3 {
		--k: var(--cmp4);
	}
	/* The colour key: a short, thick stroke of the line's colour. */
	.key {
		display: inline-block;
		flex: 0 0 auto;
		width: 18px;
		height: 5px;
		border-radius: 3px;
		background: var(--k);
	}

	/* The readout: when, then one row per line. Fixed heights, so scrubbing never moves the
	   layout and four rows always have their room. */
	.readout {
		display: grid;
		gap: 4px;
	}
	.when {
		height: 18px;
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--accent-ink);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.reads {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 8px;
	}
	.read {
		min-width: 0;
		height: 66px;
		box-sizing: border-box;
		display: grid;
		align-content: start;
		gap: 1px;
		padding: 7px 10px;
		border-radius: 14px;
		background: var(--surface-2);
	}
	/* Each card carries its line's colour down its left edge. */
	.read:not(.spare) {
		padding-left: 14px;
		box-shadow: inset 4px 0 0 var(--k);
		transition: background-color var(--ease);
	}
	.read.hl {
		background: color-mix(in srgb, var(--k) 14%, var(--surface-2));
	}
	.read.spare {
		background: transparent;
	}
	.who {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
		font-size: 0.74rem;
		font-weight: 600;
		color: var(--text-2);
		white-space: nowrap;
	}
	.rname {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.rv {
		display: flex;
		align-items: baseline;
		gap: 6px;
		min-width: 0;
		white-space: nowrap;
	}
	.rval {
		flex: 0 0 auto;
		font-size: 1.05rem;
		font-weight: 600;
		line-height: 1.2;
	}
	.rdet {
		min-width: 0;
		font-size: 0.72rem;
		color: var(--text-3);
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.where {
		min-width: 0;
		font-size: 0.7rem;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	/* Phones: the same cards, two by two. */
	.phone .reads {
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 6px;
	}
	.phone .read {
		height: 46px;
		padding: 5px 9px;
	}
	.phone .read:not(.spare) {
		padding-left: 12px;
	}
	.phone .rval {
		font-size: 0.98rem;
	}

	.axes {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		margin-bottom: -6px;
	}
	.phone .axes {
		font-size: 0.7rem;
		font-weight: 500;
		color: var(--text-3);
		margin-bottom: -2px;
	}
	.plotrow {
		display: flex;
		gap: 8px;
	}
	.yaxis {
		position: relative;
		width: 46px;
		height: var(--plot-h);
		flex-shrink: 0;
		font-size: 0.72rem;
		color: var(--text-3);
		font-variant-numeric: tabular-nums;
	}
	.phone .yaxis {
		width: 38px;
	}
	.yaxis span {
		position: absolute;
		right: 0;
		transform: translateY(-50%);
		white-space: nowrap;
	}
	.plot {
		position: relative;
		flex: 1;
		min-width: 0;
		height: var(--plot-h);
		border-bottom: 1px solid var(--border);
		cursor: crosshair;
		touch-action: pan-y;
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
	.line {
		fill: none;
		stroke: var(--k);
		stroke-width: 2.5;
		transition:
			opacity var(--ease),
			stroke-width var(--ease);
		stroke-linejoin: round;
		stroke-linecap: round;
	}
	.line.hl {
		stroke-width: 4;
	}
	.line.faded,
	.dot.faded {
		opacity: 0.25;
	}
	.cloud {
		fill: rgb(var(--cloud));
		stroke: none;
	}
	.zone {
		stroke: none;
	}
	.z-wet {
		fill: color-mix(in srgb, var(--mix) 10%, transparent);
	}
	.z-avg {
		fill: color-mix(in srgb, var(--snow) 6%, transparent);
	}
	.z-light {
		fill: color-mix(in srgb, var(--snow) 12%, transparent);
	}
	.z-dry {
		fill: color-mix(in srgb, var(--snow) 20%, transparent);
	}
	.zonename,
	.lanename {
		position: absolute;
		font-size: 0.68rem;
		font-weight: 600;
		color: var(--text-2);
		pointer-events: none;
		white-space: nowrap;
	}
	.zonename {
		left: 8px;
		transform: translateY(-50%);
	}
	.lanename {
		left: 6px;
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 1px 6px;
		border-radius: 6px;
		background: color-mix(in srgb, var(--surface) 82%, transparent);
	}
	.ref {
		position: absolute;
		left: 0;
		right: 0;
		border-top: 1px dashed color-mix(in srgb, var(--text-2) 55%, transparent);
		pointer-events: none;
	}
	.reflbl {
		position: absolute;
		left: 4px;
		transform: translateY(calc(-100% - 2px));
		padding: 0 5px;
		border-radius: 5px;
		font-size: 10px;
		font-weight: 500;
		line-height: 15px;
		color: var(--text-2);
		background: color-mix(in srgb, var(--surface) 88%, transparent);
		white-space: nowrap;
		pointer-events: none;
	}
	.fltick {
		position: absolute;
		right: 0;
		width: 14px;
		height: 4px;
		margin-top: -2px;
		border-radius: 2px 0 0 2px;
		background: var(--k);
	}
	.none {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		margin: 0;
		padding: 0 16px;
		text-align: center;
		font-size: 0.86rem;
		color: var(--text-3);
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
		width: 10px;
		height: 10px;
		margin: -5px 0 0 -5px;
		border-radius: 50%;
		background: var(--surface);
		border: 2.5px solid var(--k);
		pointer-events: none;
	}
	.xaxis {
		display: flex;
		gap: 8px;
		height: 30px;
		margin-top: -6px;
	}
	.yspace {
		width: 46px;
		flex-shrink: 0;
	}
	.phone .yspace {
		width: 38px;
	}
	.xticks {
		position: relative;
		flex: 1;
		min-width: 0;
	}
	.xticks span {
		position: absolute;
		transform: translateX(-50%);
		display: grid;
		justify-items: center;
		font-size: 0.72rem;
		color: var(--text-3);
		white-space: nowrap;
	}
	.xticks span.strong {
		font-weight: 600;
		color: var(--text);
	}
	.xticks small {
		font-size: 0.68rem;
		font-weight: 400;
		color: var(--text-3);
	}
</style>
