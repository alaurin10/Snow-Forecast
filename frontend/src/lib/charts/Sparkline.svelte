<!--
  A location's 10-day day/night snowfall in miniature. Every row on the
  Overview passes the same `max`, so bar heights compare across locations.
-->
<script lang="ts">
	import type { OverviewPeriod } from '../types.gen';
	import { roundedTopBar } from './geom';

	interface Props {
		periods: OverviewPeriod[];
		/** Shared scale top, in cm. */
		max: number;
		width?: number;
		height?: number;
		label?: string;
	}

	let { periods, max, width: fixedWidth, height = 34, label = '10-day snowfall' }: Props = $props();
	let measured = $state(0);
	const W = $derived(fixedWidth ?? measured);
	const n = $derived(Math.max(1, periods.length));
	const step = $derived(W / n);
	const bw = $derived(Math.max(1, step - 2));
	const h = (cm: number | null | undefined) =>
		max > 0 ? (Math.max(0, cm ?? 0) / max) * (height - 2) : 0;
</script>

<div class="spark" bind:clientWidth={measured}>
	{#if W > 0}
		<svg width={W} {height} role="img" aria-label={label}>
			<g class="plot" data-iw={W} data-ih={height}>
				{#each periods as p, i (p.key)}
					{#if p.kind === 'night'}
						<rect class="nightband" x={i * step} y="0" width={step} {height} />
					{/if}
					{#if (p.snow_cm ?? 0) > 0}
						<path
							class="mark"
							fill={p.kind === 'night' ? 'var(--snow-night)' : 'var(--snow)'}
							d={roundedTopBar(i * step + 1, height - h(p.snow_cm), bw, h(p.snow_cm), 2)}
						/>
					{/if}
				{/each}
				<line class="base" x1="0" x2={W} y1={height - 0.5} y2={height - 0.5} />
			</g>
		</svg>
	{/if}
</div>

<style>
	.spark {
		min-width: 0;
	}
	svg {
		display: block;
	}
	.nightband {
		fill: var(--night);
	}
	.base {
		stroke: var(--grid);
	}
</style>
