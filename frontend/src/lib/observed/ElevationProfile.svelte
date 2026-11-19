<!--
  Snow by elevation: each nearby station as a dot, its height up the side and its snow
  depth along the bottom, with this location's elevations drawn across as dashed lines.
  Higher usually means deeper; the dots show how much. Point at a dot for its name.
-->
<script lang="ts">
	import { scaleLinear } from 'd3-scale';
	import type { BandOut, NearbyStation } from '../types.gen';
	import Frame from '../charts/Frame.svelte';
	import { maxOf } from '../charts/geom';
	import { converters, elevation, snow, type UnitSystem } from '../units';

	interface Props {
		stations: NearbyStation[];
		bands: BandOut[];
		own?: string | null;
		units: UnitSystem;
		width?: number;
	}

	let { stations, bands, own = null, units, width: fixedWidth }: Props = $props();
	let measured = $state(0);
	const c = $derived(converters(units));

	const W = $derived(fixedWidth ?? measured);
	const M = { top: 10, right: 12, bottom: 24, left: 48 };
	const H = 250;
	const ih = H - M.top - M.bottom;
	const iw = $derived(Math.max(0, W - M.left - M.right));

	const pts = $derived(
		stations
			.filter((s) => s.station.elev_m !== null && s.station.depth_cm !== null)
			.map((s) => ({
				s,
				elev: c.height(s.station.elev_m) as number,
				depth: c.snow(s.station.depth_cm) as number,
				own: s.station.id === own
			}))
	);
	const elevs = $derived([...pts.map((p) => p.elev), ...bands.map((b) => c.height(b.elev_m)!)]);
	const y = $derived(
		scaleLinear()
			.domain([Math.min(...elevs), Math.max(...elevs)])
			.range([ih, 0])
			.nice(4)
	);
	const x = $derived(
		scaleLinear()
			.domain([
				0,
				maxOf(
					pts.map((p) => p.depth),
					units === 'imperial' ? 4 : 10
				)
			])
			.range([0, iw])
			.nice(4)
	);
	let hover = $state<number | null>(null);
	const ownPt = $derived(pts.findIndex((p) => p.own));
	const shown = $derived(hover ?? (ownPt >= 0 ? ownPt : null));
	const readout = $derived(
		shown === null
			? 'point at a dot'
			: `${pts[shown].s.station.name}: ${snow(pts[shown].s.station.depth_cm, units)} at ${elevation(pts[shown].s.station.elev_m, units)}`
	);

	function pick(e: PointerEvent) {
		const box = (e.currentTarget as SVGRectElement).getBoundingClientRect();
		const px = e.clientX - box.left;
		const py = e.clientY - box.top;
		let best: number | null = null;
		let bestD = 28 * 28;
		pts.forEach((p, i) => {
			const d = (x(p.depth) - px) ** 2 + (y(p.elev) - py) ** 2;
			if (d < bestD) {
				bestD = d;
				best = i;
			}
		});
		hover = best;
	}
	const fmtElev = (v: number) => v.toLocaleString('en-US');
</script>

<div bind:clientWidth={measured}>
	<Frame
		title="Snow depth by elevation"
		{readout}
		width={W}
		height={H}
		margin={M}
		{y}
		yTicks={y.ticks(4)}
		yFormat={fmtElev}
		label="Nearby stations' snow depth plotted against their elevation, with this location's elevations"
	>
		{#snippet children({ iw: plotW, ih: plotH })}
			{#each bands as b (b.band)}
				{@const by = y(c.height(b.elev_m)!)}
				<line class="band" x1="0" x2={plotW} y1={by} y2={by} />
				<text class="bandlabel" x={plotW} y={by - 4} text-anchor="end">{b.label}</text>
			{/each}
			{#each pts as p, i (p.s.station.id)}
				<circle
					class="mark dot"
					class:own={p.own}
					class:hot={hover === i}
					cx={x(p.depth)}
					cy={y(p.elev)}
					r={p.own || hover === i ? 6 : 4.5}
				/>
			{/each}
			{#if ownPt >= 0}
				{@const p = pts[ownPt]}
				<text
					class="ownlabel"
					x={x(p.depth) + (x(p.depth) > plotW * 0.6 ? -10 : 10)}
					y={y(p.elev) + 4}
					text-anchor={x(p.depth) > plotW * 0.6 ? 'end' : 'start'}>{p.s.station.name}</text
				>
			{/if}
			<rect
				class="hit"
				x="0"
				y="0"
				width={plotW}
				height={plotH}
				role="presentation"
				onpointerdown={pick}
				onpointermove={pick}
				onpointerleave={(e) => e.pointerType === 'mouse' && (hover = null)}
			/>
		{/snippet}
		{#snippet below()}
			{#each x.ticks(4) as t (t)}
				<text class="tick" x={x(t)} y={ih + 15} text-anchor="middle">{t}</text>
			{/each}
		{/snippet}
	</Frame>
	<p class="axes faint">
		Up the side: elevation ({c.heightUnit}). Along the bottom: snow depth ({c.snowUnit}).
	</p>
</div>

<style>
	.band {
		stroke: var(--text-3);
		stroke-width: 1;
		stroke-dasharray: 4 4;
		opacity: 0.7;
	}
	.bandlabel {
		fill: var(--text-3);
		font-size: 10.5px;
		font-weight: 600;
		letter-spacing: 0.03em;
		text-transform: uppercase;
	}
	.dot {
		fill: var(--snow);
		stroke: var(--surface);
		stroke-width: 1.5;
	}
	.dot.own {
		fill: var(--accent);
	}
	.dot.hot {
		stroke: var(--text);
	}
	.ownlabel {
		fill: var(--accent-ink);
		font-size: 11px;
		font-weight: 600;
	}
	.tick {
		fill: var(--text-3);
		font-size: 10.5px;
		font-variant-numeric: tabular-nums;
	}
	.hit {
		fill: transparent;
		touch-action: pan-y;
		cursor: crosshair;
	}
	.axes {
		margin: 2px 0 0;
		font-size: 0.76rem;
	}
</style>
