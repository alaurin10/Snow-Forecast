<!--
  The numbers behind the model chart: one row per model, one column per day, each cell
  shaded by how much snow, with the ensembles' range above and the models' median below.
-->
<script lang="ts">
	import { hscroll } from '../hscroll';
	import { bucket } from '../calendar';
	import type { DayRead } from '../confidence';
	import { MODEL_NAMES, modelColor } from '../models';
	import { monthDay, weekday } from '../time';
	import { converters, snowNum, type UnitSystem } from '../units';

	interface Props {
		days: DayRead[];
		models: string[];
		units: UnitSystem;
		/** How many days to show (the models thin out after ten). */
		count?: number;
	}

	let { days, models, units, count = 10 }: Props = $props();
	const c = $derived(converters(units));
	const cols = $derived(days.slice(0, count));
	const shown = $derived(
		models.filter((m) => cols.some((d) => d.models[m] !== null && d.models[m] !== undefined))
	);
	/** A model's total over the days shown, or null when it stops before the last. */
	const total = (m: string) => {
		const vals = cols.map((d) => d.models[m]);
		return vals.some((v) => v === null || v === undefined)
			? null
			: vals.reduce<number>((acc, v) => acc + (v ?? 0), 0);
	};
	const medianTotal = $derived(
		cols.some((d) => d.median === null)
			? null
			: cols.reduce<number>((acc, d) => acc + (d.median ?? 0), 0)
	);
	const num = (cm: number | null | undefined) => snowNum(cm ?? null, units);
	const range = (d: DayRead) =>
		d.lo === null || d.hi === null ? '–' : `${num(d.lo)}–${num(d.hi)}`;
</script>

<div class="table-wrap" use:hscroll>
	<table class="data models">
		<caption class="sr-only">Snow per day from each model at mid-mountain, in {c.snowUnit}</caption>
		<thead>
			<tr>
				<th scope="col">{c.snowUnit} per day</th>
				{#each cols as d, i (d.date)}
					<th scope="col"
						><span class="wd">{i === 0 ? 'Today' : weekday(d.date)}</span><span class="md faint"
							>{monthDay(d.date).split(' ')[1]}</span
						></th
					>
				{/each}
				<th scope="col" class="tot">Total</th>
			</tr>
		</thead>
		<tbody>
			<tr class="ens">
				<th scope="row">Ensembles 10–90%</th>
				{#each cols as d (d.date)}<td class="num">{range(d)}</td>{/each}
				<td></td>
			</tr>
			{#each shown as m (m)}
				{@const t = total(m)}
				<tr>
					<th scope="row"
						><i class="key" style="background: {modelColor(m)}"></i>{MODEL_NAMES[m] ?? m}</th
					>
					{#each cols as d (d.date)}
						{@const v = d.models[m]}
						<td>
							{#if v === null || v === undefined}
								<span class="faint">–</span>
							{:else}
								<span class="heat b{bucket(v)}">{num(v)}</span>
							{/if}
						</td>
					{/each}
					<td class="num tot">{t === null ? '–' : num(t)}</td>
				</tr>
			{/each}
			<tr class="median">
				<th scope="row">Models’ median</th>
				{#each cols as d (d.date)}
					<td class="num">{d.median === null ? '–' : num(d.median)}</td>
				{/each}
				<td class="num tot">{medianTotal === null ? '–' : num(medianTotal)}</td>
			</tr>
		</tbody>
	</table>
</div>

<style>
	.models th,
	.models td {
		padding: 3px 4px;
		border-bottom: 0;
		text-align: center;
	}
	.models thead th {
		padding-bottom: 6px;
		font-size: 0.78rem;
	}
	.models th:first-child {
		padding-left: 0;
		padding-right: 10px;
		font-weight: 500;
		color: var(--text);
	}
	.models thead th:first-child {
		color: var(--text-2);
		font-weight: 600;
	}
	.wd,
	.md {
		display: block;
		line-height: 1.2;
	}
	.md {
		font-weight: 500;
		font-size: 0.72rem;
	}
	.key {
		display: inline-block;
		width: 9px;
		height: 9px;
		border-radius: 50%;
		margin-right: 7px;
	}
	.heat {
		min-width: 40px;
		height: 30px;
		padding: 0 4px;
		font-size: 0.82rem;
		border-radius: 9px;
	}
	.ens td,
	.ens th:first-child {
		font-size: 0.74rem;
		color: var(--text-2);
		padding-bottom: 6px;
	}
	.median td,
	.median th:first-child {
		padding-top: 7px;
		font-weight: 700;
	}
	.models .tot {
		padding-left: 12px;
		text-align: right;
		font-weight: 600;
	}
</style>
