<!--
  Avalanche weather, day by day: the published danger where the bulletin covers a day,
  then what each day's weather does to the snowpack (new snow, drifting, rain, warming)
  and how hard it pushes in all. The grade is the app's own estimate from the forecast,
  drawn in colours unlike the danger scale's and always captioned as such; with
  HAZARD_INDEX off (`graded` false) only the facts show.
-->
<script lang="ts">
	import type { AvalancheView, OutlookDay } from '../types.gen';
	import type { LoadState } from '../load';
	import { dangerWord } from '../conditions';
	import { monthDay, weekday } from '../time';
	import type { UnitSystem } from '../units';
	import {
		cell,
		FACTOR_NAMES,
		FACTORS,
		outlookSummary,
		publishedDanger,
		stressWord
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
	}

	let { days, avy, avyLoad = 'ready', today, units, graded = true }: Props = $props();
	const summary = $derived(graded ? outlookSummary(days, today, units) : '');
	const center = $derived(
		avy?.doc?.center_id && avy.doc.center_id !== 'avcan'
			? avy.doc.center_id
			: (avy?.doc?.center ?? null)
	);
	const TREND = { rising: '↑', easing: '↓', steady: '' } as const;
	const trendMark = (t: string | null) => TREND[(t ?? 'steady') as keyof typeof TREND] ?? '';
</script>

<div class="outlook" class:plain={!graded}>
	<h2>Avalanche weather, day by day</h2>
	{#if !days.length}
		<p class="muted small">The day-by-day outlook arrives with the next forecast run.</p>
	{:else}
		{#if summary}<p class="lede">{summary}</p>{/if}
		<div class="grid" role="table" aria-label="Avalanche weather for each day">
			<div class="row head" role="row">
				<span role="columnheader">Day</span>
				<span role="columnheader">Published danger</span>
				{#if graded}<span role="columnheader">Weather stress</span>{/if}
				{#each FACTORS as f (f)}<span role="columnheader">{FACTOR_NAMES[f]}</span>{/each}
			</div>
			{#each days as d (d.date)}
				{@const lvl = publishedDanger(avy, d.date)}
				<div class="row" role="row">
					<span class="day" role="rowheader">
						<strong>{d.date === today ? 'Today' : weekday(d.date)}</strong>
						<span class="faint">{monthDay(d.date)}</span>
					</span>
					<span class="pub" class:unrated={!lvl} role="cell">
						<span class="lab">Published</span>
						{#if lvl}
							<span class="danger d{lvl}">{lvl} · {dangerWord(lvl)}</span>
						{:else if avyLoad === 'loading'}
							<span class="faint">…</span>
						{:else}
							<span class="faint none">Not rated</span>
						{/if}
					</span>
					{#if graded}
						<span
							class="stress s{d.stress}"
							role="cell"
							aria-label="Weather stress: {stressWord(d.stress)}{d.trend && d.trend !== 'steady'
								? `, ${d.trend}`
								: ''}"
						>
							<span class="lab">Weather stress</span>
							<span class="steps" aria-hidden="true"
								>{#each [1, 2, 3] as i (i)}<i class:on={i <= d.stress}></i>{/each}</span
							>
							<span class="sword" aria-hidden="true"
								>{stressWord(d.stress)}{#if trendMark(d.trend)}<span class="arrow" title={d.trend}
										>&nbsp;{trendMark(d.trend)}</span
									>{/if}</span
							>
						</span>
					{/if}
					{#each FACTORS as f (f)}
						{@const cl = cell(d, f, units)}
						<span class="fact" class:quiet={graded && cl.level === 0} role="cell">
							<span class="lab">{FACTOR_NAMES[f]}</span>
							<span class="val">
								{#if graded}
									<span class="pips p{cl.level}" aria-hidden="true"
										>{#each [1, 2, 3] as i (i)}<i class:on={i <= cl.level}></i>{/each}</span
									>
								{/if}
								<span class="num">{cl.value}</span>
							</span>
							{#if cl.detail}<span class="det faint">{cl.detail}</span>{/if}
						</span>
					{/each}
				</div>
			{/each}
		</div>
		<p class="faint small caption">
			{#if graded}
				<strong>An estimate from the forecast, not a danger rating.</strong> “Weather stress” grades how
				hard each day’s weather pushes on the snowpack, on rule-of-thumb thresholds. It can’t see the
				snowpack itself: buried weak layers stay dangerous through quiet weather.
			{/if}
			Published danger is {center ? `${center}’s` : 'the avalanche center’s'} own rating, shown only for
			the days its bulletin covers. New snow and wind are at the summit; rain and the freezing level at
			mid-mountain.
		</p>
	{/if}
</div>

<style>
	h2 {
		margin: 0 0 6px;
	}
	.lede {
		margin: 0 0 10px;
		font-size: 0.95rem;
	}
	.small {
		font-size: 0.8rem;
	}
	.caption {
		margin: 10px 0 0;
	}
	.caption strong {
		color: var(--text-2);
	}
	.grid {
		display: grid;
	}
	.row {
		display: grid;
		grid-template-columns: 92px 132px 138px repeat(4, minmax(0, 1fr));
		gap: 4px 12px;
		align-items: center;
		padding: 9px 0;
		border-top: 1px solid var(--grid);
		font-size: 0.86rem;
		min-width: 0;
	}
	.plain .row {
		grid-template-columns: 92px 132px repeat(4, minmax(0, 1fr));
	}
	.row.head {
		border-top: 0;
		padding: 0 0 6px;
		font-size: 0.74rem;
		font-weight: 600;
		color: var(--text-2);
	}
	.day {
		display: grid;
		line-height: 1.25;
	}
	.day .faint {
		font-size: 0.76rem;
	}
	.lab {
		display: none;
		font-size: 0.68rem;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-3);
	}
	.none {
		font-size: 0.8rem;
	}
	/* The grade: three steps, blue to magenta, nothing like the danger scale. */
	.stress {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 2px 8px;
		min-width: 0;
	}
	.steps {
		display: inline-flex;
		gap: 2px;
	}
	.steps i {
		width: 11px;
		height: 14px;
		border-radius: 3px;
		background: var(--surface-2);
	}
	.s1 .steps i.on {
		background: var(--stress-1);
	}
	.s2 .steps i.on {
		background: var(--stress-2);
	}
	.s3 .steps i.on {
		background: var(--stress-3);
	}
	.sword {
		font-weight: 600;
		white-space: nowrap;
	}
	.s0 .sword {
		font-weight: 500;
		color: var(--text-2);
	}
	.arrow {
		font-weight: 700;
	}
	.fact {
		display: grid;
		gap: 0;
		min-width: 0;
		line-height: 1.25;
	}
	.val {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
		font-weight: 600;
		white-space: nowrap;
	}
	.quiet .val {
		font-weight: 500;
		color: var(--text-2);
	}
	.det {
		font-size: 0.76rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.pips {
		display: inline-flex;
		flex: none;
		gap: 1.5px;
	}
	.pips i {
		width: 4px;
		height: 11px;
		border-radius: 1.5px;
		background: var(--surface-2);
	}
	.p1 i.on {
		background: var(--stress-1);
	}
	.p2 i.on {
		background: var(--stress-2);
	}
	.p3 i.on {
		background: var(--stress-3);
	}
	/* Narrower than the full grid: each day becomes a block. Its name and the grade share
	   a line, the published rating (when there is one) sits under them, then the four
	   facts two by two. */
	@media (max-width: 899px) {
		.row.head {
			display: none;
		}
		.row,
		.plain .row {
			grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
			align-items: start;
			gap: 8px 12px;
			padding: 12px 0;
		}
		.row:first-of-type {
			border-top: 0;
		}
		.day {
			grid-area: 1 / 1;
			display: flex;
			align-items: baseline;
			gap: 8px;
			font-size: 0.95rem;
		}
		.plain .day {
			grid-column: 1 / -1;
		}
		.stress {
			grid-area: 1 / 2;
			align-self: center;
		}
		.stress .lab {
			display: none;
		}
		.pub {
			grid-area: 2 / 1 / 3 / -1;
			display: flex;
			align-items: center;
			gap: 8px;
		}
		.pub.unrated {
			display: none;
		}
		.lab {
			display: block;
		}
	}
</style>
