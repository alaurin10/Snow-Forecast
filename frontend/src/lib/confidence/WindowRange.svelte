<!--
  One window's total on a line: the likely range as a band, the consensus as a tick,
  and each model as a dot in its own colour. Both windows share one scale (`max`), so
  the two bands can be compared by eye.
-->
<script lang="ts">
	import { scaleLinear } from 'd3-scale';
	import type { WindowRead } from '../confidence';
	import { MODEL_NAMES, modelColor } from '../models';
	import { converters, snow, type UnitSystem } from '../units';

	interface Props {
		read: WindowRead;
		/** The scale's top, in cm (the same for every window shown together). */
		max: number;
		units: UnitSystem;
		width?: number;
	}

	let { read, max, units, width: fixedWidth }: Props = $props();
	let measured = $state(0);
	const W = $derived(fixedWidth ?? measured);
	const c = $derived(converters(units));
	const M = { top: 6, right: 10, bottom: 18, left: 10 };
	const H = 52;
	const ih = H - M.top - M.bottom;
	const iw = $derived(Math.max(0, W - M.left - M.right));
	const top = $derived(c.snow(max) ?? 1);
	const x = $derived(
		scaleLinear()
			.domain([0, Math.max(top, units === 'imperial' ? 2 : 5)])
			.range([0, iw])
			.nice(4)
	);
	const px = (cm: number | null) => x(c.snow(cm) ?? 0);
	const label = $derived(
		`${read.label}: ${snow(read.snow_cm, units)}` +
			(read.lo !== null && read.hi !== null
				? `, likely ${snow(read.lo, units)} to ${snow(read.hi, units)}`
				: '') +
			(read.models.length
				? `. ${read.models.map((m) => `${MODEL_NAMES[m.model] ?? m.model} ${snow(m.cm, units)}`).join(', ')}`
				: '')
	);
</script>

<div class="range" bind:clientWidth={measured}>
	{#if W > 0}
		<svg width={W} height={H} role="img" aria-label={label}>
			<g class="plot" transform="translate({M.left},{M.top})" data-iw={iw} data-ih={ih}>
				<line class="track" x1="0" x2={iw} y1={ih / 2} y2={ih / 2} />
				{#if read.lo !== null && read.hi !== null}
					<rect
						class="mark band"
						x={px(read.lo)}
						y={ih / 2 - 9}
						width={Math.max(2, px(read.hi) - px(read.lo))}
						height="18"
						rx="9"
					/>
				{/if}
				{#each read.models as m (m.model)}
					<circle class="mark dot" cx={px(m.cm)} cy={ih / 2} r="4.5" fill={modelColor(m.model)} />
				{/each}
				{#if read.snow_cm !== null}
					<line
						class="mark cons"
						x1={px(read.snow_cm)}
						x2={px(read.snow_cm)}
						y1={ih / 2 - 13}
						y2={ih / 2 + 13}
					/>
				{/if}
				{#each x.ticks(4) as t (t)}
					<text class="tick" x={x(t)} y={ih + 15} text-anchor="middle">{t}</text>
				{/each}
			</g>
		</svg>
	{/if}
</div>

<style>
	.range {
		min-width: 0;
	}
	svg {
		display: block;
		overflow: visible;
	}
	.track {
		stroke: var(--grid);
		stroke-width: 2;
		stroke-linecap: round;
	}
	.band {
		fill: var(--ens);
	}
	.dot {
		stroke: var(--surface);
		stroke-width: 1.5;
	}
	.cons {
		stroke: var(--text);
		stroke-width: 2.5;
		stroke-linecap: round;
	}
	.tick {
		fill: var(--text-3);
		font-size: 10.5px;
		font-variant-numeric: tabular-nums;
	}
</style>
