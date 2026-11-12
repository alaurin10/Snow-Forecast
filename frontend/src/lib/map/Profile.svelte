<!--
  The elevation profile of a measured line: height against distance, the line coloured
  by the slope of the ground it crosses (the slope overlay's colours). Drag along it to
  read the numbers at a point; the map marks the same spot.
-->
<script lang="ts">
	import { scaleLinear } from 'd3-scale';
	import Frame from '../charts/Frame.svelte';
	import { linePath, bandPath, type Margin } from '../charts/geom';
	import type { UnitSystem } from '../units';
	import { mToFt } from '../units';
	import { distanceText, segments, type Sample } from './measure';

	interface Props {
		samples: Sample[];
		units: UnitSystem;
		/** The sample under the crosshair, or null. */
		onhover?: (i: number | null) => void;
		/** A fixed width (tests); otherwise the space it's given. */
		fixedWidth?: number;
	}

	let { samples, units, onhover, fixedWidth }: Props = $props();
	let measured = $state(0);
	const width = $derived(fixedWidth ?? measured);
	const height = 128;
	const margin: Margin = { top: 6, right: 8, bottom: 18, left: 46 };
	const ft = $derived(units === 'imperial');
	const h = (m: number) => (ft ? mToFt(m) : m);

	const iw = $derived(Math.max(0, width - margin.left - margin.right));
	const ih = height - margin.top - margin.bottom;
	const total = $derived(samples.length ? samples[samples.length - 1].d : 0);
	const x = $derived(
		scaleLinear()
			.domain([0, total || 1])
			.range([0, iw])
	);
	const y = $derived.by(() => {
		const es = samples.map((s) => h(s.elev));
		const lo = Math.min(...es);
		const hi = Math.max(...es);
		// At least 40 m (or 150 ft) of height, so a flat line doesn't look like a cliff.
		const span = Math.max(hi - lo, ft ? 150 : 40);
		const mid = (hi + lo) / 2;
		return scaleLinear()
			.domain([mid - span / 2 - span * 0.06, mid + span / 2 + span * 0.06])
			.range([ih, 0])
			.nice(4);
	});
	const ticks = $derived(y.ticks(3));
	const xs = $derived(samples.map((s) => x(s.d)));
	const ys = $derived(samples.map((s) => y(h(s.elev))));
	const floor = $derived(samples.map(() => ih));
	const area = $derived(bandPath(xs, ys, floor));
	const parts = $derived(
		segments(samples).map((g) => ({
			color: g.color,
			d: linePath(xs.slice(g.from, g.to + 1), ys.slice(g.from, g.to + 1))
		}))
	);

	let at = $state<number | null>(null);
	function pointer(px: number) {
		if (!samples.length) return;
		const d = x.invert(px);
		let best = 0;
		for (let i = 1; i < samples.length; i++)
			if (Math.abs(samples[i].d - d) < Math.abs(samples[best].d - d)) best = i;
		at = best;
		onhover?.(best);
	}
	function leave() {
		at = null;
		onhover?.(null);
	}
	const readout = $derived.by(() => {
		if (at == null) return '';
		const s = samples[at];
		const e = ft
			? `${Math.round(mToFt(s.elev)).toLocaleString('en-US')} ft`
			: `${Math.round(s.elev).toLocaleString('en-US')} m`;
		return `${distanceText(s.d, units)} · ${e} · ground ${Math.round(s.slope)}°`;
	});
	const fmt = (v: number) => (ft ? `${(v / 1000).toFixed(1)}k` : `${Math.round(v)}`);
</script>

<div class="profile" bind:clientWidth={measured}>
	<Frame
		title="Profile"
		{readout}
		{width}
		{height}
		{margin}
		{y}
		yTicks={ticks}
		yFormat={fmt}
		crossX={at == null ? null : xs[at]}
		onpointer={pointer}
		onleave={leave}
		label="Elevation profile, coloured by the slope of the ground"
	>
		<path class="mark area" d={area} />
		{#each parts as p, i (i)}
			<path class="mark seg" d={p.d} stroke={p.color} />
		{/each}
		{#snippet below()}
			<text class="axis" x="0" y={ih + 13}>0</text>
			<text class="axis" x={iw} y={ih + 13} text-anchor="end">{distanceText(total, units)}</text>
			<text class="axis unit" x={-margin.left + 2} y="-1">{ft ? 'ft' : 'm'}</text>
		{/snippet}
	</Frame>
</div>

<style>
	.profile {
		width: 100%;
		min-width: 0;
	}
	.area {
		fill: color-mix(in srgb, var(--text) 9%, transparent);
	}
	.seg {
		fill: none;
		stroke-width: 2.5;
		stroke-linejoin: round;
		stroke-linecap: round;
	}
	.axis {
		fill: var(--text-3);
		font-size: 10.5px;
		font-variant-numeric: tabular-nums;
	}
</style>
