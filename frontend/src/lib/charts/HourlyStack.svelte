<!--
  The hourly stack: six charts on one time axis with one shared crosshair.
  Each chart's header shows its own value at the crosshair hour, so a finger
  never covers the data and no chart needs a second axis.
-->
<script lang="ts">
	import { scaleLinear } from 'd3-scale';
	import type { BandOut } from '../types.gen';
	import { crosshair } from '../crosshair.svelte';
	import { converters, type UnitSystem } from '../units';
	import { dateOf, dayHour, hourOf, weekday } from '../time';
	import Frame from './Frame.svelte';
	import { bandPath, clamp, finite, linePath, maxOf, roundedTopBar, runs } from './geom';

	interface Props {
		band: BandOut;
		bands: BandOut[];
		units: UnitSystem;
		/** Fixed width (tests); otherwise the container's width. */
		width?: number;
	}

	let { band, bands, units, width: fixedWidth }: Props = $props();

	let measured = $state(0);
	let days = $state<5 | 10>(5);

	const W = $derived(fixedWidth ?? measured);
	const c = $derived(converters(units));
	const h = $derived(band.hourly);
	const n = $derived(Math.min(days * 24, h.t.length));
	const idx = $derived(Array.from({ length: n }, (_, i) => i));
	const M = { top: 4, right: 10, bottom: 4, left: 40 };
	const iw = $derived(Math.max(0, W - M.left - M.right));
	const x = $derived(scaleLinear().domain([0, n]).range([0, iw]));
	const bw = $derived(n ? iw / n : 0);
	const gap = $derived(bw > 4 ? 1 : 0.4);
	const mid = (i: number) => x(i + 0.5);
	const xs = $derived(idx.map(mid));

	const ci = $derived(clamp(crosshair.index, 0, Math.max(0, n - 1)));
	const crossX = $derived(n ? mid(ci) : null);
	const nights = $derived(runs(h.is_day.slice(0, n), (v) => v === 0));
	const midnights = $derived(idx.filter((i) => i > 0 && hourOf(h.t[i]) === 0));

	function onpointer(px: number) {
		crosshair.set(clamp(Math.floor(x.invert(px)), 0, n - 1));
	}
	const onleave = () => crosshair.reset();

	function fmt(v: number | null | undefined, digits = 0): string {
		return v === null || v === undefined ? '–' : v.toFixed(digits);
	}

	// 1. Snowfall
	const snow = $derived(idx.map((i) => c.snow(h.snow_cm[i])));
	const cumSnow = $derived(
		snow.reduce<number[]>((acc, v, i) => [...acc, (i ? acc[i - 1] : 0) + (v ?? 0)], [])
	);
	const H = 92;
	const ih = H - M.top - M.bottom;
	const ySnow = $derived(
		scaleLinear()
			.domain([0, maxOf(snow, units === 'imperial' ? 0.3 : 0.8)])
			.range([ih, 0])
			.nice(3)
	);

	// 2. Precipitation (water) and its chance
	const water = $derived(idx.map((i) => c.water(h.water_mm[i])));
	const yWater = $derived(
		scaleLinear()
			.domain([0, maxOf(water, units === 'imperial' ? 0.04 : 1)])
			.range([ih, 0])
			.nice(3)
	);
	const pcolor: Record<string, string> = {
		snow: 'var(--snow)',
		mix: 'var(--mix)',
		rain: 'var(--rain)',
		none: 'var(--text-3)'
	};

	// 3. Temperature
	const temp = $derived(idx.map((i) => c.temp(h.temp_c[i])));
	const tLo = $derived(idx.map((i) => c.temp(h.temp_lo[i])));
	const tHi = $derived(idx.map((i) => c.temp(h.temp_hi[i])));
	const yTemp = $derived.by(() => {
		const vals = finite([...tLo, ...tHi, ...temp, c.freezing]);
		const pad = units === 'imperial' ? 3 : 2;
		return scaleLinear()
			.domain([Math.min(...vals) - pad, Math.max(...vals) + pad])
			.range([ih, 0])
			.nice(4);
	});

	// 4. Snow level (freezing level minus a fixed offset), with the band elevations
	const level = $derived(idx.map((i) => c.height(h.snow_level_m[i])));
	const offset = $derived.by(() => {
		for (let i = 0; i < h.t.length; i++) {
			const f = h.fl_m[i];
			const s = h.snow_level_m[i];
			if (f !== null && s !== null && s > 0) return f - s;
		}
		return 305;
	});
	const lvLo = $derived(
		idx.map((i) => c.height(h.fl_lo[i] === null ? null : Math.max(0, h.fl_lo[i]! - offset)))
	);
	const lvHi = $derived(
		idx.map((i) => c.height(h.fl_hi[i] === null ? null : Math.max(0, h.fl_hi[i]! - offset)))
	);
	const refs = $derived(
		bands.map((b) => ({ label: b.label, v: c.height(b.elev_m) ?? 0, band: b.band }))
	);
	// Skip a reference label that would sit on top of the one above it.
	const refLabelled = (k: number): boolean =>
		k === refs.length - 1 || yLevel(refs[k].v) - yLevel(refs[k + 1].v) >= 12;
	const yLevel = $derived.by(() => {
		const vals = finite([...lvLo, ...lvHi, ...level, ...refs.map((r) => r.v)]);
		return scaleLinear()
			.domain([Math.max(0, Math.min(...vals) * 0.9), Math.max(...vals) * 1.05])
			.range([ih, 0])
			.nice(4);
	});

	// 5. Wind
	const wind = $derived(idx.map((i) => c.speed(h.wind_kmh[i])));
	const gust = $derived(idx.map((i) => c.speed(h.gust_kmh[i])));
	const yWind = $derived(
		scaleLinear()
			.domain([0, maxOf([...gust, ...wind], units === 'imperial' ? 30 : 50)])
			.range([ih, 0])
			.nice(3)
	);
	// Every 3 h, or every 6 h when the chart is too narrow for that.
	const arrowEvery = $derived(bw * 3 < 12 ? 6 : 3);
	const arrows = $derived(
		idx.filter((i) => hourOf(h.t[i]) % arrowEvery === 0 && h.wdir[i] !== null)
	);

	// 6. Sky: three strips
	const sky = $derived([
		{ name: 'High', key: 'cloud_high' as const },
		{ name: 'Mid', key: 'cloud_mid' as const },
		{ name: 'Low', key: 'cloud_low' as const }
	]);

	const ticks = (s: { ticks: (n: number) => number[] }, k = 3) => s.ticks(k);
	const at = (arr: (number | null)[], i: number) => (i < arr.length ? arr[i] : null);
</script>

<div class="stack" bind:clientWidth={measured}>
	<div class="head">
		<div class="when num">
			{#if n}
				{ci === 0 ? 'Now' : dayHour(h.t[ci])}
			{/if}
		</div>
		<div class="seg" role="group" aria-label="Hours shown">
			<button aria-pressed={days === 5} onclick={() => (days = 5)}>5 days</button>
			<button aria-pressed={days === 10} onclick={() => (days = 10)}>10 days</button>
		</div>
	</div>

	{#snippet nightBands(ih: number)}
		{#each nights as [a, b] (a)}
			<rect class="night" x={x(a)} y="0" width={x(b) - x(a)} height={ih} />
		{/each}
		{#each midnights as m (m)}
			<line class="midnight" x1={x(m)} x2={x(m)} y1="0" y2={ih} />
		{/each}
	{/snippet}

	<Frame
		title="Snowfall"
		readout={`${fmt(at(snow, ci), c.snowDigits)} ${c.snowUnit} · ${fmt(cumSnow[ci], c.snowDigits)} ${c.snowUnit} since now`}
		width={W}
		height={H}
		margin={M}
		y={ySnow}
		yTicks={ticks(ySnow)}
		yFormat={(v) => v.toFixed(units === 'imperial' ? 1 : 0)}
		{crossX}
		{onpointer}
		{onleave}
	>
		{#snippet children({ ih })}
			{@render nightBands(ih)}
			{#each idx as i (i)}
				{@const v = snow[i]}
				{#if v && v > 0}
					<path
						class="mark"
						fill="var(--snow)"
						d={roundedTopBar(x(i) + gap / 2, ySnow(v), Math.max(0.6, bw - gap), ih - ySnow(v), 2)}
					/>
				{/if}
			{/each}
		{/snippet}
	</Frame>

	<Frame
		title="Precipitation"
		readout={`${fmt(at(water, ci), c.waterDigits)} ${c.waterUnit} · ${h.ptype[ci] ?? '–'} · ${h.pop[ci] ?? '–'}% chance`}
		width={W}
		height={H + 14}
		margin={{ ...M, bottom: 18 }}
		y={yWater}
		yTicks={ticks(yWater)}
		yFormat={(v) => v.toFixed(units === 'imperial' ? 2 : 0)}
		{crossX}
		{onpointer}
		{onleave}
	>
		{#snippet children({ ih })}
			{@render nightBands(ih)}
			{#each idx as i (i)}
				{@const v = water[i]}
				{#if v && v > 0}
					<path
						class="mark"
						fill={pcolor[h.ptype[i]] ?? 'var(--text-3)'}
						d={roundedTopBar(x(i) + gap / 2, yWater(v), Math.max(0.6, bw - gap), ih - yWater(v), 2)}
					/>
				{/if}
			{/each}
		{/snippet}
		{#snippet below({ ih })}
			<!-- Chance of precipitation: its own 0–100% shading row, not a second axis. -->
			{#each idx as i (i)}
				<rect
					class="mark"
					x={x(i)}
					y={ih + 6}
					width={Math.max(0.5, bw)}
					height="8"
					fill="var(--snow)"
					opacity={(h.pop[i] ?? 0) / 100}
				/>
			{/each}
			<text class="tick" x="-6" y={ih + 10} dy="0.32em" text-anchor="end">%</text>
		{/snippet}
	</Frame>

	<Frame
		title="Temperature"
		readout={`${fmt(at(temp, ci))}${c.tempUnit} · models ${fmt(at(tLo, ci))}–${fmt(at(tHi, ci))}`}
		width={W}
		height={H}
		margin={M}
		y={yTemp}
		yTicks={ticks(yTemp, 4)}
		yFormat={(v) => `${v}°`}
		{crossX}
		{onpointer}
		{onleave}
	>
		{#snippet children({ ih })}
			{@render nightBands(ih)}
			<path
				class="mark band"
				fill="var(--temp)"
				d={bandPath(
					xs,
					tLo.map((v) => (v === null ? null : yTemp(v))),
					tHi.map((v) => (v === null ? null : yTemp(v)))
				)}
			/>
			<line class="freeze" x1="0" x2={iw} y1={yTemp(c.freezing)} y2={yTemp(c.freezing)} />
			<path
				class="mark line"
				stroke="var(--temp)"
				d={linePath(
					xs,
					temp.map((v) => (v === null ? null : yTemp(v)))
				)}
			/>
		{/snippet}
	</Frame>

	<Frame
		title="Snow level"
		readout={`${at(level, ci) === null ? '–' : Math.round(at(level, ci)! / (units === 'imperial' ? 100 : 50)) * (units === 'imperial' ? 100 : 50)} ${c.heightUnit}`}
		width={W}
		height={H + 16}
		margin={M}
		y={yLevel}
		yTicks={ticks(yLevel, 3)}
		yFormat={(v) =>
			v === 0 ? '0' : units === 'imperial' ? `${(v / 1000).toFixed(v % 1000 ? 1 : 0)}k` : `${v}`}
		{crossX}
		{onpointer}
		{onleave}
	>
		{#snippet children({ ih })}
			{@render nightBands(ih)}
			{#each refs as r, k (r.band)}
				{#if yLevel(r.v) >= 0 && yLevel(r.v) <= ih}
					<line class="ref" x1="0" x2={iw} y1={yLevel(r.v)} y2={yLevel(r.v)} />
					{#if refLabelled(k)}
						<text class="reflabel" x={iw - 2} y={yLevel(r.v) - 3} text-anchor="end">{r.label}</text>
					{/if}
				{/if}
			{/each}
			<path
				class="mark band"
				fill="var(--level)"
				d={bandPath(
					xs,
					lvLo.map((v) => (v === null ? null : yLevel(v))),
					lvHi.map((v) => (v === null ? null : yLevel(v)))
				)}
			/>
			<path
				class="mark line"
				stroke="var(--level)"
				d={linePath(
					xs,
					level.map((v) => (v === null ? null : yLevel(v)))
				)}
			/>
		{/snippet}
	</Frame>

	<Frame
		title="Wind"
		readout={`${fmt(at(wind, ci))} ${c.speedUnit} · gusts ${fmt(at(gust, ci))}`}
		width={W}
		height={H + 12}
		margin={{ ...M, top: 16 }}
		y={yWind}
		yTicks={ticks(yWind)}
		{crossX}
		{onpointer}
		{onleave}
	>
		{#snippet children({ ih })}
			{@render nightBands(ih)}
			<path
				class="mark band"
				fill="var(--wind)"
				d={bandPath(
					xs,
					wind.map((v) => (v === null ? null : yWind(v))),
					gust.map((v) => (v === null ? null : yWind(v)))
				)}
			/>
			<path
				class="mark line"
				stroke="var(--wind)"
				d={linePath(
					xs,
					wind.map((v) => (v === null ? null : yWind(v)))
				)}
			/>
			{#each arrows as i (i)}
				<!-- Direction the wind blows toward (wdir is where it comes from). -->
				<g class="arrow" transform="translate({mid(i)},-8) rotate({(h.wdir[i] ?? 0) + 180})">
					<path d="M0,-5 L3,2 L0,0.5 L-3,2 Z" />
				</g>
			{/each}
		{/snippet}
	</Frame>

	<Frame
		title="Sky (cloud cover)"
		readout={`high ${h.cloud_high[ci] ?? '–'}% · mid ${h.cloud_mid[ci] ?? '–'}% · low ${h.cloud_low[ci] ?? '–'}%`}
		width={W}
		height={54}
		margin={{ ...M, bottom: 22 }}
		{crossX}
		{onpointer}
		{onleave}
	>
		{#snippet children({ ih })}
			{#each sky as row, r (row.key)}
				{@const rh = ih / 3}
				<text class="tick" x="-6" y={r * rh + rh / 2} dy="0.32em" text-anchor="end">{row.name}</text
				>
				{#each idx as i (i)}
					<rect
						class="mark"
						x={x(i)}
						y={r * rh + 1}
						width={Math.max(0.5, bw)}
						height={rh - 2}
						fill="rgb(var(--cloud))"
						opacity={((h[row.key][i] ?? 0) / 100) * 0.85}
					/>
				{/each}
			{/each}
		{/snippet}
		{#snippet below({ ih })}
			<text class="tick daylabel" x="0" y={ih + 14}>Now</text>
			{#each midnights as m (m)}
				{#if x(m) > 28}
					<text class="tick daylabel" x={x(m) + 3} y={ih + 14}>{weekday(dateOf(h.t[m]))}</text>
				{/if}
			{/each}
		{/snippet}
	</Frame>
</div>

<style>
	.stack {
		display: grid;
		gap: 10px;
		min-width: 0;
	}
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
	}
	.when {
		font-size: 1rem;
		font-weight: 600;
	}
	.night {
		fill: var(--night);
	}
	.midnight {
		stroke: var(--grid);
		stroke-width: 1;
	}
	.band {
		opacity: 0.16;
	}
	.line {
		fill: none;
		stroke-width: 2;
		stroke-linejoin: round;
	}
	.freeze {
		stroke: var(--text-3);
		stroke-dasharray: 4 3;
		stroke-width: 1;
	}
	.ref {
		stroke: var(--text-3);
		stroke-dasharray: 2 3;
		stroke-width: 1;
	}
	.reflabel {
		fill: var(--text-2);
		font-size: 10px;
	}
	.arrow path {
		fill: var(--text-2);
	}
	.tick {
		fill: var(--text-3);
		font-size: 10.5px;
	}
	.daylabel {
		fill: var(--text-2);
		font-weight: 600;
	}
</style>
