<!-- Ten days of day and night snowfall as paired bars coloured by precipitation type.
     The night half sits on a shaded strip; each day is labelled under its bars. -->
<script lang="ts">
	import type { OverviewPeriod } from '../types.gen';
	import { dayPairs, type Half } from '../daybars';

	interface Props {
		periods: OverviewPeriod[];
		/** Shared scale (cm) so heights compare across locations. */
		max: number;
		label: string;
		/** Bar area height in px. */
		height?: number;
	}

	let { periods, max, label, height = 30 }: Props = $props();
	const days = $derived(dayPairs(periods));
	const h = (x: Half | null) =>
		x && x.cm > 0 ? Math.max(2, Math.round((x.cm / max) * height)) : 0;
</script>

<div class="bars" role="img" aria-label={label} style:--h="{height}px">
	{#each days as d, i (d.date)}
		<div class="day" class:later={i >= 5}>
			<div class="pair">
				<span class="half"
					><span class="bar {d.day?.kind ?? 'none'}" style:height="{h(d.day)}px"></span></span
				>
				<span class="half night"
					><span class="bar {d.night?.kind ?? 'none'}" style:height="{h(d.night)}px"></span></span
				>
			</div>
			<span class="lbl" class:weekend={d.weekend}>{d.short}</span>
		</div>
	{/each}
</div>

<style>
	.bars {
		display: flex;
		gap: 3px;
		min-width: 0;
	}
	.day {
		flex: 1;
		min-width: 0;
		display: grid;
		gap: 2px;
	}
	.day.later {
		opacity: 0.5;
	}
	.pair {
		height: var(--h);
		display: flex;
		align-items: flex-end;
	}
	.half {
		flex: 1;
		height: 100%;
		display: flex;
		align-items: flex-end;
		padding: 0 1px;
	}
	.half.night {
		background: var(--surface-2);
		border-radius: 3px 3px 0 0;
	}
	.bar {
		width: 100%;
		border-radius: 2px 2px 1px 1px;
	}
	.bar.snow {
		background: var(--snow);
	}
	.bar.heavy {
		background: var(--snow-heavy);
	}
	.bar.mix {
		background: var(--mix);
	}
	.bar.rain {
		background: var(--rain);
	}
	.lbl {
		font-size: 9px;
		line-height: 10px;
		text-align: center;
		font-weight: 600;
		color: var(--text-3);
	}
	.lbl.weekend {
		color: var(--accent);
	}
</style>
