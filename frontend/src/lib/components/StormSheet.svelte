<!-- One storm cycle in a popup: every location it reaches, with its snow each day of the
     storm and its total. Picking a day opens that location's day. -->
<script lang="ts">
	import { bucket } from '../calendar';
	import { dayPairs } from '../daybars';
	import type { StormCycle } from '../stormcycles';
	import { monthDay, weekday } from '../time';
	import type { OverviewRow } from '../types.gen';
	import { converters, snow, snowNum, type UnitSystem } from '../units';
	import Sheet from './Sheet.svelte';

	interface Props {
		cycle: StormCycle;
		rows: OverviewRow[];
		units: UnitSystem;
		/** Open one location's day. */
		onday: (id: string, name: string, date: string) => void;
		onclose: () => void;
	}

	let { cycle, rows, units, onday, onclose }: Props = $props();
	const c = $derived(converters(units));

	const day = (d: string) => `${weekday(d)} ${monthDay(d)}`;
	const when = $derived(
		cycle.start === cycle.end ? day(cycle.start) : `${day(cycle.start)} – ${day(cycle.end)}`
	);
	const dates = $derived(
		[
			...new Set(
				rows
					.flatMap((r) => (r.periods ?? []).map((p) => p.date))
					.filter((d) => d >= cycle.start && d <= cycle.end)
			)
		].sort()
	);
	const lines = $derived(
		cycle.locations.map((s) => {
			const r = rows.find((x) => x.id === s.id);
			const byDate = new Map(dayPairs(r?.periods ?? [], 16).map((d) => [d.date, d.total]));
			return { s, cells: dates.map((d) => ({ d, cm: byDate.get(d) ?? 0 })) };
		})
	);
	const shown = (cm: number) => Number(snowNum(cm, units)) > 0;
</script>

<Sheet
	title={when}
	sub="Storm · {cycle.locations.length}
	{cycle.locations.length === 1 ? 'location' : 'locations'} · snow per day, {c.snowUnit}"
	width={560}
	{onclose}
>
	<div class="scroll">
		<div class="grid" style:--n={dates.length}>
			<span></span>
			{#each dates as d (d)}
				<span class="dh">{weekday(d).slice(0, 2)}<small>{Number(d.slice(8))}</small></span>
			{/each}
			<span class="dh tot">Total</span>
			{#each lines as { s, cells } (s.id)}
				<span class="name"
					>{s.name}{#if s.wet}<small> · some rain</small>{/if}</span
				>
				{#each cells as { d, cm } (d)}
					<button
						class="heat b{shown(cm) ? bucket(cm) : 0}"
						onclick={() => onday(s.id, s.name, d)}
						aria-label="{s.name}, {day(d)}: {snow(cm, units)}. Details"
						>{shown(cm) ? snowNum(cm, units) : ''}</button
					>
				{/each}
				<strong class="num tot">{snowNum(s.total_cm, units)}</strong>
			{/each}
		</div>
	</div>
	<p class="hint">Pick a day for its details.</p>
</Sheet>

<style>
	.scroll {
		overflow-x: auto;
	}
	.grid {
		min-width: calc(130px + var(--n) * 40px);
		display: grid;
		grid-template-columns: minmax(0, 1fr) repeat(var(--n), 44px) 52px;
		align-items: center;
		gap: 6px 4px;
	}
	.dh {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--text-2);
		text-align: center;
	}
	.dh small {
		display: block;
		font-weight: 400;
		color: var(--text-3);
	}
	.name {
		min-width: 0;
		font-size: 0.88rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.name small {
		font-weight: 400;
		color: var(--text-2);
	}
	.heat {
		height: 34px;
		border: 0;
		border-radius: 10px;
		font: 700 0.8rem var(--font-num);
		cursor: pointer;
	}
	.heat:hover {
		outline: 2px solid var(--accent);
		outline-offset: 1px;
	}
	.tot {
		text-align: right;
	}
	strong.tot {
		font-size: 0.95rem;
	}
	.hint {
		margin: 0;
		font-size: 0.78rem;
		color: var(--text-3);
	}
	@media (max-width: 640px) {
		.grid {
			grid-template-columns: minmax(0, 1fr) repeat(var(--n), 36px) 40px;
		}
	}
</style>
