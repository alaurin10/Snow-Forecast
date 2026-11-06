<!-- One chart for every metric. Cards above it switch the metric and show each value at
     the hovered step; the range picker sets both the span and the step size. Every
     piece of text has a fixed size so sweeping across the chart never moves the layout. -->
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

	interface Props {
		band: BandOut;
		/** All bands, for the base, mid and summit lines on the freezing-level view. */
		bands: BandOut[];
		units: UnitSystem;
		/** Click on a step: the time of its first hour. */
		onpick?: (t: string) => void;
	}

	let { band, bands, units, onpick }: Props = $props();
	const c = $derived(converters(units));
	const ranges = $derived(availableRanges(band.hourly.t.length));
	let range = $state<Range>(5);
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

	// Scale for the chosen metric, in display units.
	const view = $derived.by(() => {
		const val = (st: Step): number | null => {
			if (metric === 'precip') return c.snow(st.precip);
			if (metric === 'temp') return c.temp(st.temp);
			if (metric === 'wind') return c.speed(st.wind);
			if (metric === 'cloud') return st.cloud;
			return c.height(st.fl);
		};
		const vals = steps.map(val).filter((v): v is number => v !== null);
		let axis;
		if (metric === 'precip')
			axis = niceAxis(0, Math.max(units === 'imperial' ? 0.2 : 0.5, ...vals));
		else if (metric === 'temp') {
			const spread = steps
				.flatMap((st) => [c.temp(st.tempLo), c.temp(st.tempHi)])
				.filter((v): v is number => v !== null);
			const lo = Math.min(c.freezing, ...vals, ...spread);
			const hi = Math.max(c.freezing, ...vals, ...spread);
			axis = niceAxis(lo - 2, hi + 2, 4);
		} else if (metric === 'wind') {
			const g = steps.map((st) => c.speed(st.gust)).filter((v): v is number => v !== null);
			axis = niceAxis(0, Math.max(10, ...vals, ...g), 4);
		} else if (metric === 'cloud') axis = { min: 0, max: 100, ticks: [0, 25, 50, 75, 100] };
		else {
			const e = elevs.map((x) => c.height(x.m) ?? 0);
			for (const st of steps)
				for (const v of [c.height(st.flLo), c.height(st.flHi)]) if (v !== null) e.push(v);
			axis = niceAxis(Math.min(...vals, ...e) * 0.9, Math.max(...vals, ...e) * 1.05, 4);
		}
		return { val, axis };
	});
	const y = (v: number) => H - ((v - view.axis.min) / (view.axis.max - view.axis.min)) * H;
	const pct = (v: number) => `${((y(v) / H) * 100).toFixed(2)}%`;
	const tickLabel = (v: number) => {
		if (metric === 'precip') return `${v} ${c.snowUnit}`;
		if (metric === 'temp') return `${v}°`;
		if (metric === 'cloud') return `${v}%`;
		if (metric === 'fl')
			return units === 'imperial'
				? `${(v / 1000).toLocaleString('en-US')}k ft`
				: `${v.toLocaleString('en-US')} m`;
		return `${v}`;
	};
	const axisTitle = $derived(
		{
			precip: `Precipitation ${per[STEP[R]]} (${c.snowUnit})`,
			temp: `Temperature (${c.tempUnit})`,
			wind: `Wind (${c.speedUnit})`,
			cloud: 'Cloud cover (%)',
			fl: `Freezing level (${c.heightUnit})`
		}[metric]
	);

	// Running snow total on the right axis for the precipitation view.
	const cumAxis = $derived(
		niceAxis(0, Math.max(1, c.snow(steps[steps.length - 1]?.cum ?? 0) ?? 1), 4)
	);
	const yCum = (v: number) => H - (v / cumAxis.max) * H;

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
		let line: string;
		let line2 = '';
		let area = '';
		let band = '';
		if (metric === 'precip') {
			const bw = W * 0.72;
			steps.forEach((st, k) => {
				const v = c.snow(st.precip) ?? 0;
				const hh = Math.min(H, (v / view.axis.max) * H);
				if (hh > 0.2 && st.kind !== 'none')
					bars[st.kind] +=
						`M${(k * W + W * 0.14).toFixed(2)} ${(H - hh).toFixed(1)}h${bw.toFixed(2)}v${hh.toFixed(1)}h-${bw.toFixed(2)}z`;
			});
			line = linePath((st) => c.snow(st.cum), yCum);
		} else {
			line = linePath(view.val, y);
			if (metric === 'wind') line2 = linePath((st) => c.speed(st.gust), y);
			if (metric === 'cloud' && line)
				area = `M${(W / 2).toFixed(1)} ${H}${line.replace('M', 'L')}L${(1000 - W / 2).toFixed(1)} ${H}Z`;
		}
		// Model spread as a band behind the line.
		const range =
			metric === 'temp'
				? (st: Step) => [c.temp(st.tempLo), c.temp(st.tempHi)]
				: metric === 'fl'
					? (st: Step) => [c.height(st.flLo), c.height(st.flHi)]
					: null;
		if (range) {
			const ok = steps
				.map((st, k) => ({ x: k * W + W / 2, r: range(st) }))
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
		return { bars, line, line2, area, band };
	});

	// Lower panel: chance of precipitation as bars (coloured by type) over cloud cover.
	const lower = $derived.by(() => {
		const H2 = 100;
		const bars: Record<string, string> = { snow: '', heavy: '', mix: '', rain: '', none: '' };
		const bw = W * 0.56;
		steps.forEach((st, k) => {
			const hh = ((st.pop ?? 0) / 100) * H2;
			if (hh > 0.5)
				bars[st.kind] +=
					`M${(k * W + W * 0.22).toFixed(2)} ${(H2 - hh).toFixed(1)}h${bw.toFixed(2)}v${hh.toFixed(1)}h-${bw.toFixed(2)}z`;
		});
		const pts = steps
			.map((st, k) =>
				st.cloud === null ? null : `${(k * W + W / 2).toFixed(1)} ${(H2 - st.cloud).toFixed(1)}`
			)
			.filter((p): p is string => p !== null);
		const cloud = pts.length
			? `M${(W / 2).toFixed(1)} ${H2}L${pts.join('L')}L${(1000 - W / 2).toFixed(1)} ${H2}Z`
			: '';
		const shadeL = steps
			.map((st, k) =>
				st.night ? `M${(k * W).toFixed(2)} 0h${W.toFixed(2)}v${H2}h-${W.toFixed(2)}z` : ''
			)
			.join('');
		return { bars, cloud, shade: shadeL };
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
	const grid = $derived(view.axis.ticks.map((v) => `M0 ${y(v).toFixed(1)}H1000`).join(''));
	const refs = $derived.by(() => {
		if (metric === 'temp') return [{ label: `${c.freezing}${c.tempUnit}`, top: pct(c.freezing) }];
		if (metric === 'fl')
			return elevs.map((e) => ({
				label: `${e.label} ${elevation(e.m, units)}`,
				top: pct(c.height(e.m) ?? 0)
			}));
		return [];
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
	const KIND: Record<string, string> = {
		snow: 'snow',
		heavy: 'heavy snow',
		mix: 'mixed',
		rain: 'rain',
		none: 'dry'
	};
	const zone = (m: number | null) => {
		if (m === null || !elevs.length) return '';
		const lo = elevs[0].m;
		const hi = elevs[elevs.length - 1].m;
		return m < lo ? 'below base' : m > hi ? 'above summit' : 'between base and summit';
	};
	const amount = (cm: number, st: Step) =>
		st.kind === 'rain'
			? `${(c.water(cm * 10) ?? 0).toFixed(c.waterDigits)} ${c.waterUnit}`
			: `${(c.snow(cm) ?? 0).toFixed(STEP[R] <= 3 ? c.snowDigits + 1 : c.snowDigits)} ${c.snowUnit}`;

	const cards = $derived.by(() => {
		if (!s) return [];
		const cum = `${(c.snow(s.cum) ?? 0).toFixed(c.snowDigits)} ${c.snowUnit} so far`;
		const t = c.temp(s.temp);
		return [
			{
				id: 'precip' as Metric,
				label: 'Precipitation',
				color: 'var(--snow)',
				value: amount(s.precip, s),
				sub: `${s.pop === null ? KIND[s.kind] : `${Math.round(s.pop)}% chance`} · ${cum}`
			},
			{
				id: 'temp' as Metric,
				label: 'Temperature',
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
				color: 'var(--wind)',
				value: `${compass(s.dir)} ${speed(s.wind, units)}`,
				sub: `gusts ${speed(s.gust, units)}`
			},
			{
				id: 'cloud' as Metric,
				label: 'Cloud cover',
				color: 'rgb(var(--cloud))',
				value: s.cloud === null ? '–' : `${Math.round(s.cloud)}%`,
				sub:
					s.cloud === null
						? ''
						: s.cloud > 85
							? 'overcast'
							: s.cloud > 50
								? 'mostly cloudy'
								: 'partly sunny'
			},
			{
				id: 'fl' as Metric,
				label: 'Freezing level',
				color: 'var(--level)',
				value: elevation(s.fl, units),
				sub: zone(s.fl)
			}
		];
	});

	const hoverY = $derived.by(() => {
		if (!s) return '0%';
		if (metric === 'precip') return `${((yCum(c.snow(s.cum) ?? 0) / H) * 100).toFixed(2)}%`;
		const v = view.val(s);
		return v === null ? '50%' : pct(v);
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
		<h2>Forecast</h2>
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
				<span class="mlabel"><i style:background={k.color}></i>{k.label}</span>
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
			{#each view.axis.ticks as v (v)}<span style:top={pct(v)}>{tickLabel(v)}</span>{/each}
		</div>
		<div
			class="plot"
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
				<path d={grid} class="grid" />
				<path d={midnights} class="midnight" />
				<path d={paths.bars.snow} class="b-snow" />
				<path d={paths.bars.heavy} class="b-heavy" />
				<path d={paths.bars.mix} class="b-mix" />
				<path d={paths.bars.rain} class="b-rain" />
				<path d={paths.band} class="band m-{metric}" />
				<path d={paths.area} class="area m-{metric}" />
				<path d={paths.line2} class="line2 m-{metric}" />
				<path d={paths.line} class="line m-{metric}" />
			</svg>
			{#if conf}
				<div class="conf" style:left={conf.left}>
					{#if conf.roomy}<span>Less certain →</span>{/if}
				</div>
			{/if}
			{#each refs as r (r.label)}
				<div class="ref" style:top={r.top}><span>{r.label}</span></div>
			{/each}
			{#if s}
				<div class="cursor" style:left="{((hv + 0.5) / N) * 100}%"></div>
				<div class="dot m-{metric}" style:left="{((hv + 0.5) / N) * 100}%" style:top={hoverY}></div>
			{/if}
		</div>
		<div class="yaxis right">
			{#if metric === 'precip'}
				{#each cumAxis.ticks as v (v)}<span style:top="{((yCum(v) / H) * 100).toFixed(2)}%"
						>{v}</span
					>{/each}
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
				{#each ['snow', 'heavy', 'mix', 'rain', 'none'] as k (k)}
					<path d={lower.bars[k]} class="pop pop-{k}" />
				{/each}
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
		<span><i class="sw night"></i>Night</span>
		{#if metric === 'precip'}
			<span><i class="sw" style:background="var(--snow)"></i>Snow</span>
			<span><i class="sw" style:background="var(--snow-heavy)"></i>Heavy snow (6+ in in a day)</span
			>
			<span><i class="sw" style:background="var(--mix)"></i>Mixed</span>
			<span><i class="sw" style:background="var(--rain)"></i>Rain (liquid)</span>
			<span>Line: running snow total, right axis</span>
		{:else if metric === 'temp'}
			<span
				>{STEP[R] === 12 ? 'Days show the high, nights the low · ' : ''}Dashed line: freezing</span
			>
		{:else if metric === 'wind'}
			<span>Solid: strongest sustained wind · Dashed: peak gust</span>
		{:else if metric === 'cloud'}
			<span>Average share of the sky covered</span>
		{:else}
			<span>Dashed lines: this location's elevations</span>
		{/if}
		{#if metric === 'temp' || metric === 'fl'}<span
				><i class="sw band-sw m-{metric}"></i>Range across the weather models</span
			>{/if}
		<span class="lower-key"
			><i class="sw cloud-sw"></i>Lower panel: cloud cover, and chance of precipitation as bars by
			type</span
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
	/* One row of cards that scrolls sideways; fixed sizes so values never reflow. */
	.cards {
		display: flex;
		flex-wrap: nowrap;
		gap: 8px;
		overflow-x: auto;
		scrollbar-width: thin;
		padding-bottom: 2px;
		-webkit-overflow-scrolling: touch;
	}
	.mcard {
		flex: 1 0 196px;
		max-width: 260px;
		height: 86px;
		box-sizing: border-box;
		overflow: hidden;
		text-align: left;
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		padding: 11px 14px;
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
		display: block;
		font-size: 0.75rem;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
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
	.band {
		stroke: none;
		fill-opacity: 0.16;
	}
	.band.m-temp {
		fill: var(--temp);
	}
	.band.m-fl {
		fill: var(--level);
	}
	.band-sw.m-temp {
		background: color-mix(in srgb, var(--temp) 25%, transparent);
	}
	.band-sw.m-fl {
		background: color-mix(in srgb, var(--level) 25%, transparent);
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
	.cloudarea {
		fill: rgb(var(--cloud) / 0.28);
		stroke: rgb(var(--cloud) / 0.7);
		stroke-width: 1.5;
	}
	.pop-snow {
		fill: var(--snow);
	}
	.pop-heavy {
		fill: var(--snow-heavy);
	}
	.pop-mix {
		fill: var(--mix);
	}
	.pop-rain {
		fill: var(--rain);
	}
	.pop-none {
		fill: rgb(var(--cloud) / 0.6);
	}
	.cloud-sw {
		background: rgb(var(--cloud) / 0.35);
		border: 1px solid rgb(var(--cloud) / 0.7);
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
	.ref {
		position: absolute;
		left: 0;
		right: 0;
		border-top: 1.5px dashed var(--text-2);
		pointer-events: none;
	}
	.ref span {
		position: absolute;
		right: 6px;
		bottom: 3px;
		font-size: 0.7rem;
		font-weight: 600;
		background: color-mix(in srgb, var(--surface) 90%, transparent);
		padding: 1px 6px;
		border-radius: 6px;
		white-space: nowrap;
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
		.mcard {
			flex: 0 0 132px;
			height: 74px;
			padding: 9px 11px;
		}
		.mval {
			font-size: 1.05rem;
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
