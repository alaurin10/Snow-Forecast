<!--
  Snowfall per 12-hour period for 10 days. Night bars are darker and sit on a
  shaded band, so day/night never depends on color alone. The whisker is the
  ensemble 10–90% range. Tap a bar for the period's details.
-->
<script lang="ts">
	import { scaleBand, scaleLinear } from 'd3-scale';
	import type { PeriodOut } from '../types.gen';
	import { converters, type UnitSystem } from '../units';
	import Frame from './Frame.svelte';
	import { maxOf, roundedTopBar } from './geom';

	interface Props {
		periods: PeriodOut[];
		units: UnitSystem;
		selected?: string | null;
		onselect?: (p: PeriodOut) => void;
		width?: number;
	}

	let { periods, units, selected = null, onselect, width: fixedWidth }: Props = $props();
	let measured = $state(0);

	const W = $derived(fixedWidth ?? measured);
	const c = $derived(converters(units));
	const M = { top: 18, right: 6, bottom: 34, left: 32 };
	const H = 210;
	const ih = H - M.top - M.bottom;
	const iw = $derived(Math.max(0, W - M.left - M.right));
	const x = $derived(
		scaleBand<string>()
			.domain(periods.map((p) => p.key))
			.range([0, iw])
			.paddingInner(0.18)
			.paddingOuter(0.06)
	);
	const snow = $derived(periods.map((p) => c.snow(p.snow_cm)));
	const p10 = $derived(periods.map((p) => c.snow(p.ens?.p10 ?? null)));
	const p90 = $derived(periods.map((p) => c.snow(p.ens?.p90 ?? null)));
	const y = $derived(
		scaleLinear()
			.domain([0, maxOf([...snow, ...p90], units === 'imperial' ? 1 : 2.5)])
			.range([ih, 0])
			.nice(4)
	);
	const labelMin = $derived(units === 'imperial' ? 0.5 : 1);
	const step = $derived(x.step());
	const bwid = $derived(x.bandwidth());
	const total = $derived(snow.slice(0, 10).reduce<number>((a, v) => a + (v ?? 0), 0));
	const dates = $derived.by(() => {
		const out: { date: string; label: string; x: number; hi: number | null }[] = [];
		for (const p of periods) {
			const x0 = (x(p.key) ?? 0) + bwid / 2;
			const last = out.at(-1);
			if (last && last.date === p.date) {
				last.x = (last.x + x0) / 2;
				if (p.tmax_c !== null) last.hi = Math.max(last.hi ?? -999, p.tmax_c);
			} else {
				const label =
					p.label === 'Tonight' || p.label === 'Overnight'
						? p.label
						: p.label.replace(' night', '');
				out.push({ date: p.date, label, x: x0, hi: p.tmax_c });
			}
		}
		// Drop a label that would overlap the one before it (about 6 px per character).
		const kept: typeof out = [];
		for (const d of out) {
			const prev = kept.at(-1);
			if (prev && d.x - prev.x < ((prev.label.length + d.label.length) * 6) / 2 + 4) {
				if (kept.length === 1) kept[0] = d; // prefer the full day over a partial first one
				continue;
			}
			kept.push(d);
		}
		return kept;
	});
	// On narrow charts, print a value only where the bar beats both neighbours.
	const showValue = (i: number): boolean => {
		const v = snow[i];
		if (v === null || v < labelMin) return false;
		if (step >= 26) return true;
		return (snow[i - 1] ?? 0) <= v && (snow[i + 1] ?? 0) < v;
	};

	function activate(p: PeriodOut, e?: KeyboardEvent) {
		if (e && e.key !== 'Enter' && e.key !== ' ') return;
		e?.preventDefault();
		onselect?.(p);
	}
</script>

<div bind:clientWidth={measured}>
	<Frame
		title="Snowfall, day and night"
		readout={`next 5 days ${total.toFixed(c.snowDigits)} ${c.snowUnit}`}
		width={W}
		height={H}
		margin={M}
		{y}
		yTicks={y.ticks(4)}
		yFormat={(v) => v.toFixed(units === 'imperial' && v % 1 ? 1 : 0)}
		label="Snowfall per day and night period with the ensemble 10 to 90 percent range"
	>
		{#snippet children({ ih })}
			{#each periods as p, i (p.key)}
				{@const x0 = x(p.key) ?? 0}
				{@const v = snow[i]}
				{@const cx = x0 + bwid / 2}
				{#if p.kind === 'night'}
					<rect class="nightband" x={x0 - (step - bwid) / 2} y="0" width={step} height={ih} />
				{/if}
				{#if v !== null && v > 0}
					<path
						class="mark"
						fill={p.kind === 'night' ? 'var(--snow-night)' : 'var(--snow)'}
						d={roundedTopBar(x0, y(v), bwid, ih - y(v))}
					/>
				{/if}
				{#if p10[i] !== null && p90[i] !== null && (p90[i] ?? 0) > 0}
					<g class="whisker mark-group">
						<line class="mark" x1={cx} x2={cx} y1={y(p10[i]!)} y2={y(p90[i]!)} />
						<line class="mark" x1={cx - 3} x2={cx + 3} y1={y(p90[i]!)} y2={y(p90[i]!)} />
						<line class="mark" x1={cx - 3} x2={cx + 3} y1={y(p10[i]!)} y2={y(p10[i]!)} />
					</g>
				{/if}
				{#if v !== null && showValue(i)}
					<text
						class="value num"
						x={cx}
						y={Math.min(y(v), y(p90[i] ?? 0)) - 4}
						text-anchor="middle"
					>
						{v.toFixed(c.snowDigits)}
					</text>
				{/if}
				{#if selected === p.key}
					<rect class="sel" x={x0 - 2} y="-2" width={bwid + 4} height={ih + 4} rx="4" />
				{/if}
			{/each}
		{/snippet}
		{#snippet below({ ih })}
			{#each dates as d (d.date)}
				<text class="day" x={d.x} y={ih + 13} text-anchor="middle">{d.label}</text>
				{#if d.hi !== null}
					<text class="hilo num" x={d.x} y={ih + 26} text-anchor="middle">
						{Math.round(c.temp(d.hi) ?? 0)}°
					</text>
				{/if}
			{/each}
			<!-- Hit targets: the whole column, bigger than the bar. -->
			{#each periods as p (p.key)}
				{@const x0 = x(p.key) ?? 0}
				<rect
					class="hit"
					x={x0 - (step - bwid) / 2}
					y="-16"
					width={step}
					height={ih + 44}
					role="button"
					tabindex="0"
					aria-label={`${p.label}: ${p.snow_cm === null ? 'no data' : `${(c.snow(p.snow_cm) ?? 0).toFixed(c.snowDigits)} ${c.snowUnit}`}`}
					onclick={() => activate(p)}
					onkeydown={(e) => activate(p, e)}
				/>
			{/each}
		{/snippet}
	</Frame>
	<div class="legend">
		<span><i class="sw" style="background: var(--snow)"></i>Day</span>
		<span><i class="sw" style="background: var(--snow-night)"></i>Night</span>
		<span><i class="whisk"></i>Ensemble 10–90%</span>
	</div>
</div>

<style>
	.nightband {
		fill: var(--night);
	}
	.whisker line {
		stroke: var(--text);
		stroke-width: 1.2;
		opacity: 0.6;
	}
	.value {
		fill: var(--text);
		font-size: 11px;
		font-weight: 600;
	}
	.day {
		fill: var(--text-2);
		font-size: 10.5px;
		font-weight: 600;
	}
	.hilo {
		fill: var(--text-3);
		font-size: 10.5px;
	}
	.sel {
		fill: none;
		stroke: var(--focus);
		stroke-width: 1.5;
	}
	.hit {
		fill: transparent;
		cursor: pointer;
	}
	.hit:focus-visible {
		outline: none;
		stroke: var(--focus);
		stroke-width: 2;
	}
	.legend {
		display: flex;
		gap: 14px;
		flex-wrap: wrap;
		font-size: 0.78rem;
		color: var(--text-2);
		margin-top: 4px;
	}
	.sw {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 2px;
		margin-right: 5px;
		vertical-align: -1px;
	}
	.whisk {
		display: inline-block;
		width: 2px;
		height: 11px;
		background: var(--text-2);
		margin: 0 6px 0 4px;
		vertical-align: -1px;
	}
</style>
