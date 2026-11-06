<!-- The next days of snow (a week by default): one bar per day with its amount on top, coloured by
     precipitation type. Kept simple so a row reads at a glance. -->
<script lang="ts">
	import type { OverviewPeriod } from '../types.gen';
	import { dailyTotals } from '../daybars';
	import { snowNum, type UnitSystem } from '../units';

	interface Props {
		periods: OverviewPeriod[];
		/** Shared scale (cm) so heights compare across locations. */
		max: number;
		units: UnitSystem;
		label: string;
		/** How many days to show (bars pair the first 2 × days periods). */
		days?: number;
	}

	let { periods, max, units, label, days: n = 7 }: Props = $props();
	const days = $derived(dailyTotals(periods, n));
	const H = 44;
	const h = (cm: number) => (cm > 0.1 ? Math.max(3, Math.round((Math.min(cm, max) / max) * H)) : 0);
	// Hide amounts that round to zero at display precision.
	const shown = (cm: number) => Number(snowNum(cm, units)) > 0;
</script>

<div class="week" role="img" aria-label={label} style:--n={n}>
	{#each days as d (d.date)}
		<div class="day">
			<span class="amt num" class:dim={!shown(d.cm)}
				>{shown(d.cm) ? snowNum(d.cm, units) : '–'}</span
			>
			<span class="track"><span class="bar {d.kind}" style:height="{h(d.cm)}px"></span></span>
			<span class="lbl" class:weekend={d.weekend}>{d.label}</span>
		</div>
	{/each}
</div>

<style>
	.week {
		display: grid;
		grid-template-columns: repeat(var(--n), minmax(0, 1fr));
		gap: 6px;
	}
	.day {
		display: grid;
		justify-items: center;
		gap: 4px;
		min-width: 0;
	}
	.amt {
		font-size: 0.8rem;
		font-weight: 600;
		line-height: 1;
	}
	.amt.dim {
		color: var(--text-3);
		font-weight: 400;
	}
	.track {
		width: 100%;
		max-width: 40px;
		height: 44px;
		display: flex;
		align-items: flex-end;
		border-bottom: 2px solid var(--surface-2);
	}
	.bar {
		width: 100%;
		border-radius: 6px 6px 0 0;
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
		font-size: 0.72rem;
		color: var(--text-3);
		white-space: nowrap;
	}
	.lbl.weekend {
		color: var(--accent);
		font-weight: 600;
	}
</style>
