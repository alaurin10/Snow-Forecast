<!--
  Avalanche weather, day by day: what each day's weather does to the snowpack (new snow,
  drifting, rain, warming) and how hard it pushes in all. Each day is a tile: its name,
  the published danger where the bulletin covers it, the day's grade, then a line for
  each factor that is pushing. The grade is the app's own estimate from the forecast,
  drawn in colours unlike the danger scale's and explained in a key under the days; with
  HAZARD_INDEX off (`graded` false) only the facts show, all four every day.
-->
<script lang="ts">
	import type { AvalancheView, OutlookDay, OutlookSteps } from '../types.gen';
	import type { LoadState } from '../load';
	import { dangerWord } from '../conditions';
	import { monthDay, weekday } from '../time';
	import type { UnitSystem } from '../units';
	import {
		activeFactors,
		cell,
		FACTOR_NAMES,
		FACTORS,
		outlookSummary,
		publishedDanger,
		STRESS_MEANINGS,
		stressWord,
		thresholds
	} from './outlook';

	interface Props {
		days: OutlookDay[];
		avy: AvalancheView | null;
		avyLoad?: LoadState;
		/** Today's date at the location (YYYY-MM-DD). */
		today: string;
		units: UnitSystem;
		/** Whether the app's own grade is shown (the server's HAZARD_INDEX). */
		graded?: boolean;
		/** The grade's thresholds; absent in snapshots built before they were sent. */
		steps?: OutlookSteps | null;
	}

	let { days, avy, avyLoad = 'ready', today, units, graded = true, steps = null }: Props = $props();
	const summary = $derived(graded ? outlookSummary(days, today, units) : '');
	const table = $derived(steps ? thresholds(steps, units) : []);
	const center = $derived(
		avy?.doc?.center_id && avy.doc.center_id !== 'avcan'
			? avy.doc.center_id
			: (avy?.doc?.center ?? null)
	);
	const rated = $derived(avyLoad !== 'loading' && days.some((d) => publishedDanger(avy, d.date)));
</script>

{#snippet meter(n: number)}
	<span class="meter m{n}" aria-hidden="true"
		>{#each [1, 2, 3] as i (i)}<i class:on={i <= n}></i>{/each}</span
	>
{/snippet}

<div class="outlook" class:plain={!graded}>
	<h2>Avalanche weather, day by day</h2>
	{#if !days.length}
		<p class="muted small">The day-by-day outlook arrives with the next forecast run.</p>
	{:else}
		{#if summary}<p class="lede">{summary}</p>{/if}
		<ul class="days">
			{#each days as d (d.date)}
				{@const lvl = avyLoad === 'loading' ? null : publishedDanger(avy, d.date)}
				{@const shown = graded ? activeFactors(d) : FACTORS}
				{@const name = d.date === today ? 'Today' : weekday(d.date)}
				<li
					class="day"
					aria-label="{name} {monthDay(d.date)}{graded
						? `, ${stressWord(d.stress)} weather loading`
						: ''}"
				>
					<div class="head">
						<strong class="name">{name}</strong>
						<span class="date">{monthDay(d.date)}</span>
						{#if lvl}
							<span class="danger d{lvl}" title="{center ?? 'Avalanche center'} danger rating"
								>{lvl} · {dangerWord(lvl)}</span
							>
						{/if}
						{#if graded}<span class="chip s{d.stress}">{stressWord(d.stress)}</span>{/if}
					</div>
					{#if shown.length}
						<dl class="facts">
							{#each shown as f (f)}
								{@const cl = cell(d, f, units)}
								<div class="fact">
									<dt>{FACTOR_NAMES[f]}</dt>
									<dd class="val">{cl.value}</dd>
									<dd class="det" title={cl.detail}>{cl.detail}</dd>
									{#if graded}
										<dd class="lv" aria-label="{FACTOR_NAMES[f]}: {stressWord(cl.level)}">
											{@render meter(cl.level)}
										</dd>
									{/if}
								</div>
							{/each}
						</dl>
					{:else}
						<p class="calm">Calm</p>
					{/if}
				</li>
			{/each}
		</ul>
		<div class="key">
			{#if graded}
				<p>
					<strong>Weather loading</strong> is how hard each day's weather stresses the snowpack, estimated
					from the forecast. It isn't a danger rating, and it can't see the snowpack itself: buried weak
					layers stay dangerous through quiet weather. A day takes its strongest factor, one level higher
					when two are Strong.
				</p>
				<div class="scale">
					{#each [0, 1, 2, 3] as n (n)}
						{@render meter(n)}
						<span class="word">{stressWord(n)}</span>
						<span>{STRESS_MEANINGS[n]}</span>
					{/each}
				</div>
				{#if table.length}
					<details>
						<summary>See the numbers behind each level</summary>
						<div class="thr-wrap">
							<table class="thr">
								<thead>
									<tr>
										<td></td>
										{#each [1, 2, 3] as n (n)}<th scope="col">{stressWord(n)}</th>{/each}
									</tr>
								</thead>
								<tbody>
									{#each table as row (row.factor)}
										<tr>
											<th scope="row">{FACTOR_NAMES[row.factor]}</th>
											{#each [0, 1, 2] as i (i)}<td>{row.steps[i] ?? '–'}</td>{/each}
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</details>
				{/if}
			{/if}
			<p>
				New snow and wind are at the summit; rain and warming at mid-mountain.
				{#if rated}
					The coloured badge is {center ? `${center}’s` : 'the avalanche center’s'} own danger rating,
					on the days its bulletin covers.
				{/if}
			</p>
		</div>
	{/if}
</div>

<style>
	h2 {
		margin: 0 0 6px;
	}
	.lede {
		margin: 0 0 12px;
		font-size: 0.95rem;
	}
	.small {
		font-size: 0.8rem;
	}
	.days {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
		gap: 8px;
	}
	/* Each day its own tile, so days part at a glance. */
	.day {
		display: grid;
		align-content: start;
		gap: 6px;
		padding: 10px 12px;
		border-radius: 12px;
		background: color-mix(in srgb, var(--surface-2) 70%, transparent);
		min-width: 0;
	}
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 8px;
	}
	.name {
		font-family: var(--font-num);
		font-size: 1.05rem;
		font-weight: 800;
	}
	.date {
		font-size: 0.78rem;
		color: var(--text-3);
	}
	.head .danger {
		font-size: 0.7rem;
		padding: 0 7px;
	}
	/* The grade: blue to magenta, nothing like the danger scale. */
	.chip {
		margin-left: auto;
		padding: 2px 10px;
		border-radius: 999px;
		font-size: 0.78rem;
		font-weight: 700;
		white-space: nowrap;
		color: #fff;
	}
	.chip.s0 {
		background: var(--surface);
		color: var(--text-2);
		font-weight: 600;
	}
	.chip.s1 {
		background: var(--stress-1);
	}
	.chip.s2 {
		background: var(--stress-2);
	}
	.chip.s3 {
		background: var(--stress-3);
	}
	/* One line per factor, every line the same height; the columns line up from day to
	   day. Nothing wraps: the context gives way first, with an ellipsis. */
	.facts {
		display: grid;
		grid-template-columns: 52px minmax(88px, max-content) minmax(0, 1fr) auto;
		column-gap: 6px;
		row-gap: 3px;
		align-items: baseline;
		margin: 0;
	}
	.plain .facts {
		grid-template-columns: 52px minmax(88px, max-content) minmax(0, 1fr);
	}
	.fact {
		display: contents;
	}
	dt {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--text-3);
		white-space: nowrap;
	}
	dd {
		margin: 0;
		min-width: 0;
	}
	.val {
		font-family: var(--font-num);
		font-variant-numeric: tabular-nums;
		font-size: 0.9rem;
		font-weight: 700;
		white-space: nowrap;
	}
	.det {
		font-size: 0.76rem;
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.lv {
		align-self: center;
		display: flex;
	}
	.calm {
		margin: 0;
		font-size: 0.8rem;
		color: var(--text-3);
	}
	.meter {
		display: inline-flex;
		flex: none;
		gap: 2px;
	}
	.meter i {
		width: 6px;
		height: 12px;
		border-radius: 2px;
		/* Empty steps show on the tile and on the card, in both themes. */
		background: color-mix(in srgb, var(--text-3) 28%, transparent);
	}
	.m1 i.on {
		background: var(--stress-1);
	}
	.m2 i.on {
		background: var(--stress-2);
	}
	.m3 i.on {
		background: var(--stress-3);
	}
	/* The key, under the days. */
	.key {
		display: grid;
		gap: 8px;
		margin-top: 14px;
		padding-top: 12px;
		border-top: 1px solid var(--grid);
		font-size: 0.78rem;
		color: var(--text-3);
	}
	.key p {
		margin: 0;
	}
	.key strong {
		color: var(--text-2);
	}
	.scale {
		display: grid;
		grid-template-columns: auto auto minmax(0, 1fr);
		align-items: center;
		gap: 5px 8px;
	}
	.word {
		font-weight: 650;
		color: var(--text-2);
		white-space: nowrap;
	}
	summary {
		cursor: pointer;
		font-weight: 600;
		color: var(--text-2);
	}
	.thr-wrap {
		overflow-x: auto;
		margin-top: 6px;
	}
	.thr {
		border-collapse: collapse;
		width: 100%;
		font-size: 0.74rem;
	}
	.thr th,
	.thr td {
		text-align: left;
		vertical-align: top;
		padding: 4px 8px 4px 0;
		border-top: 1px solid var(--grid);
		color: var(--text-2);
	}
	.thr thead th,
	.thr thead td {
		border-top: 0;
		font-weight: 650;
	}
	.thr tbody th {
		font-weight: 600;
		white-space: nowrap;
	}
</style>
