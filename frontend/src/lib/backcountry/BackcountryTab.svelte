<!--
  The Backcountry tab, in the order a tour gets planned: the avalanche center's
  bulletin as published, then the days ahead (what the weather does to the snowpack,
  day by day), then where the wind is putting snow, then the weather for being out in.
  Snow Watch never says whether a tour is safe: the one thing it grades is the weather
  (see Outlook.svelte), and it says so.
-->
<script lang="ts">
	import type { LoadState } from '../load';
	import type { AvalancheView, Snapshot } from '../types.gen';
	import { compass } from '../conditions';
	import { dateOf, dayHour } from '../time';
	import { elevation, snow, speed, type UnitSystem } from '../units';
	import DangerPyramid from './DangerPyramid.svelte';
	import LoadingRose from './LoadingRose.svelte';
	import Outlook from './Outlook.svelte';
	import TouringTable from './TouringTable.svelte';

	interface Props {
		snap: Snapshot;
		avy: AvalancheView | null;
		avyLoad?: LoadState;
		units: UnitSystem;
		/** Whether the app's own weather-stress grade is shown (the server's HAZARD_INDEX). */
		graded?: boolean;
	}

	let { snap, avy, units, avyLoad = 'ready', graded = true }: Props = $props();

	const today = $derived(dateOf(snap.now));
	const bc = $derived(snap.backcountry ?? null);
	const ridge = $derived(snap.ridge ?? null);
	const hours = $derived(snap.bands[2].hourly.t);
	const ridgeMax = $derived.by(() => {
		if (!ridge) return null;
		let best: { i: number; v: number } | null = null;
		ridge.kmh.slice(0, 48).forEach((v, i) => {
			if (v !== null && (!best || v > best.v)) best = { i, v };
		});
		return best as { i: number; v: number } | null;
	});
	const roses = $derived(
		(bc?.rose ?? []).filter((r) => r.window === 'past72' || r.window === 'next48')
	);
</script>

<div class="bc">
	<section class="card">
		<DangerPyramid view={avy} tz={snap.location.tz} {today} load={avyLoad} />
	</section>

	{#if bc}
		<section class="card">
			<Outlook days={bc.outlook ?? []} {avy} {avyLoad} {today} {units} {graded} />
		</section>

		<section class="card">
			<h2>Where the wind is putting snow</h2>
			<div class="wind">
				<div class="facts">
					{#if ridge}
						<div>
							<span class="eyebrow">Ridge wind now</span>
							<span class="big num">{speed(ridge.kmh[0], units)}</span>
							<span class="muted small">from the {compass(ridge.dir[0])}</span>
						</div>
						{#if ridgeMax}
							<div>
								<span class="eyebrow">Strongest, next 48 h</span>
								<span class="big num">{speed(ridgeMax.v, units)}</span>
								<span class="muted small"
									>{compass(ridge.dir[ridgeMax.i])}, {dayHour(hours[ridgeMax.i])}</span
								>
							</div>
						{/if}
					{/if}
					<div>
						<span class="eyebrow">New snow at the summit</span>
						<span class="big num">{snow(bc.storm.past72_cm, units)}</span>
						<span class="muted small"
							>in the last 72 h · {snow(bc.storm.next48_cm, units)} in the next 48</span
						>
					</div>
				</div>
				<div class="roses">
					{#each roses as r (r.window)}
						<LoadingRose
							rose={r}
							title={r.window === 'past72' ? 'Last 72 h' : 'Next 48 h'}
							{units}
						/>
					{/each}
				</div>
			</div>
			<p class="faint small">
				Wedges show where snow-carrying wind came from; it drifts onto the opposite (lee) slopes.
				{#if ridge}
					The wind is the free-air wind at {elevation(ridge.level_m, units)}, from the 850 and 700
					hPa levels (the dashed line on the hourly wind chart).
				{:else}
					No free-air wind in this run; the roses use the summit wind.
				{/if}
			</p>
		</section>

		<section class="card">
			<h2>Touring weather</h2>
			<TouringTable {snap} {units} />
		</section>
	{/if}

	<p class="faint small note">
		Snow Watch doesn't judge whether a tour is safe. Read the avalanche center's forecast, and
		decide in the field.
	</p>
</div>

<style>
	.bc {
		display: grid;
		gap: 16px;
	}
	h2 {
		margin: 0 0 10px;
	}
	.small {
		font-size: 0.82rem;
	}
	.wind {
		display: grid;
		gap: 16px 28px;
		align-items: center;
	}
	.facts {
		display: grid;
		gap: 14px;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
	}
	.facts > div {
		display: grid;
		gap: 1px;
		align-content: start;
	}
	.big {
		font-family: var(--font-num);
		font-size: 1.5rem;
		font-weight: 600;
		line-height: 1.15;
		letter-spacing: -0.02em;
	}
	.roses {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
	}
	@media (min-width: 900px) {
		.wind {
			grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
		}
		.facts {
			grid-template-columns: 1fr;
		}
	}
	.note {
		margin: 0 4px;
	}
	@media (max-width: 640px) {
		.bc {
			gap: 12px;
		}
	}
</style>
