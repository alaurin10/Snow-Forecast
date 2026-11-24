<!-- Compare: the locations in the comparison, one row each. The name is the chart's switch:
     tap it to draw or hide the location's line (a filled swatch in the line's colour when
     drawn, an empty ring when not). Each row also gives the location's band and elevation
     and a summary of the days the chart shows. Edit removes and reorders; Add brings in
     more. -->
<script module lang="ts">
	import type { DayCell, Summary } from '../compare';

	export interface RowView {
		id: string;
		name: string;
		/** The line's colour slot, or -1 when the line is off. */
		slot: number;
		state: 'ok' | 'loading' | 'error' | 'nodata';
		elev_m: number | null;
		bandLabel: string;
		/** The location's days (for the timeline's bars). */
		cells: DayCell[];
		summary: Summary | null;
		/** "updated 9 h ago" for an old forecast, else null. */
		stale: string | null;
	}
</script>

<script lang="ts">
	import { summaryText, type CompareMetric } from '../compare';
	import { converters, elevation, type UnitSystem } from '../units';
	import { viewport } from '../viewport.svelte';

	interface Props {
		rows: RowView[];
		metric: CompareMetric;
		units: UnitSystem;
		sort: 'mine' | 'snow';
		/** The comparison holds as many locations as it can. */
		full: boolean;
		editing?: boolean;
		onsort: () => void;
		ontoggle: (id: string) => void;
		onremove: (id: string) => void;
		onmove: (id: string, by: -1 | 1) => void;
		onadd: () => void;
		/** Pointing at a row with a mouse (its line stands out), or leaving it (null). */
		onhighlight?: (id: string | null) => void;
		/** The location that stands out on the chart. */
		hl?: string | null;
	}

	let {
		rows,
		metric,
		units,
		sort,
		full,
		editing = $bindable(false),
		onsort,
		ontoggle,
		onremove,
		onmove,
		onadd,
		onhighlight,
		hl = null
	}: Props = $props();

	const phone = $derived(viewport.phone);
	const c = $derived(converters(units));
	const sumHead = $derived(
		{
			snow: `Total, ${c.snowUnit}`,
			temp: 'High/low',
			wind: `Top gust, ${c.speedUnit}`,
			fl: `Lowest, ${c.heightUnit}`,
			slr: 'Average',
			cloud: 'Average'
		}[metric]
	);
</script>

<div class="cr" class:phone class:editing>
	<div class="row head">
		<button
			class="sortbtn"
			onclick={onsort}
			aria-label="Order: {sort === 'mine' ? 'my order' : 'most snow first'}. Change."
		>
			<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
				><path d="M8 5v14M8 19l-3-3M8 19l3-3M16 19V5M16 5l-3 3M16 5l3 3" /></svg
			>
			{sort === 'mine' ? 'My order' : 'Most snow'}
		</button>
		<span class="sum" title="Over the days the chart shows">{sumHead}</span>
	</div>

	<ul class="list">
		{#each rows as r, i (r.id)}
			<li
				class="row"
				class:hl={hl === r.id && r.slot >= 0}
				onpointerenter={(e) => e.pointerType === 'mouse' && onhighlight?.(r.id)}
				onpointerleave={(e) => e.pointerType === 'mouse' && onhighlight?.(null)}
			>
				<div class="name">
					{#if editing}
						<span class="who"
							><i class="sw" class:off={r.slot < 0} data-slot={r.slot}></i><span class="lname"
								>{r.name}</span
							></span
						>
					{:else}
						<button
							class="who"
							aria-pressed={r.slot >= 0}
							aria-label="{r.name}: {r.slot >= 0 ? 'line drawn' : 'line hidden'}. {r.slot >= 0
								? 'Hide'
								: 'Draw'} its line."
							title={r.slot >= 0 ? 'Hide its line' : 'Draw its line'}
							onclick={() => ontoggle(r.id)}
						>
							<i class="sw" class:off={r.slot < 0} data-slot={r.slot}></i>
							<span class="lname">{r.name}</span>
						</button>
					{/if}
					<small class="sub"
						>{#if r.state === 'loading'}Loading…{:else if r.state === 'nodata'}No forecast yet{:else if r.state === 'error'}Couldn’t
							load its forecast{:else}{phone ? '' : `${r.bandLabel} · `}{elevation(
								r.elev_m,
								units
							)}{/if}{#if r.stale}<span class="stale">{` · ${r.stale}`}</span>{/if}</small
					>
				</div>
				{#if editing}
					<div class="edits">
						<button
							class="ebtn"
							onclick={() => onmove(r.id, -1)}
							aria-label="Move {r.name} up"
							disabled={i === 0}>↑</button
						>
						<button
							class="ebtn"
							onclick={() => onmove(r.id, 1)}
							aria-label="Move {r.name} down"
							disabled={i === rows.length - 1}>↓</button
						>
						<button class="ebtn remove" onclick={() => onremove(r.id)} aria-label="Remove {r.name}"
							>Remove</button
						>
					</div>
				{:else}
					<span class="sum num">{summaryText(r.summary, metric, units, true)}</span>
				{/if}
			</li>
		{/each}
	</ul>

	<div class="foot">
		<button class="add" onclick={onadd} disabled={full || editing}>
			<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
				><path d="M12 5v14M5 12h14" /></svg
			>
			Add location
		</button>
		<span class="faint full" class:shown={full}>Up to 8</span>
		<button class="edit" aria-pressed={editing} onclick={() => (editing = !editing)}
			>{editing ? 'Done' : 'Edit'}</button
		>
	</div>
</div>

<style>
	.cr {
		display: grid;
		gap: 6px;
		min-width: 0;
	}
	.row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		min-width: 0;
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 2px;
	}
	/* The row being pointed at, while its line stands out on the chart. */
	.list .row {
		min-height: 40px;
		margin: 0 -8px;
		padding: 2px 8px;
		border-radius: 12px;
		transition: background-color var(--ease);
	}
	.list .row.hl {
		background: var(--hover);
	}
	.name {
		flex: 1 1 auto;
		min-width: 0;
		display: flex;
		align-items: baseline;
		gap: 8px;
	}
	.sum {
		flex: 0 0 auto;
		text-align: right;
		font-size: 0.9rem;
		font-weight: 600;
		white-space: nowrap;
	}
	.head .sum {
		font-size: 0.74rem;
		color: var(--text-2);
	}
	.sortbtn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 32px;
		padding: 0 10px 0 6px;
		margin-left: -6px;
		border: 0;
		border-radius: 999px;
		background: transparent;
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--text-2);
		cursor: pointer;
	}
	.sortbtn:hover {
		background: var(--hover);
		color: var(--text);
	}
	.who {
		flex: 0 1 auto;
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
		max-width: 70%;
		padding: 2px 0;
		border: 0;
		background: transparent;
		text-align: left;
		font-size: 0.9rem;
		font-weight: 600;
		color: var(--text);
	}
	button.who {
		cursor: pointer;
		min-height: 34px;
		border-radius: 8px;
	}
	button.who:hover .lname {
		text-decoration: underline;
		text-decoration-color: var(--text-3);
		text-underline-offset: 3px;
	}
	.lname {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* The swatch: filled in the line's colour while it's drawn, an empty ring when not. */
	.sw {
		flex: 0 0 auto;
		width: 12px;
		height: 12px;
		border-radius: 50%;
		box-sizing: border-box;
		background: var(--k, var(--text-3));
	}
	.sw[data-slot='0'] {
		--k: var(--cmp1);
	}
	.sw[data-slot='1'] {
		--k: var(--cmp2);
	}
	.sw[data-slot='2'] {
		--k: var(--cmp3);
	}
	.sw[data-slot='3'] {
		--k: var(--cmp4);
	}
	.sw.off {
		background: transparent;
		border: 2px solid var(--text-3);
	}
	.sub {
		flex: 1 1 0;
		min-width: 0;
		font-size: 0.76rem;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.stale {
		color: var(--warn-ink);
	}
	.edits {
		flex: 0 0 auto;
		display: flex;
		gap: 6px;
	}
	.ebtn {
		min-width: 40px;
		min-height: 32px;
		padding: 0 12px;
		border: 0;
		border-radius: 999px;
		background: var(--surface-2);
		color: var(--text-2);
		font-size: 0.82rem;
		font-weight: 600;
		cursor: pointer;
	}
	.ebtn:disabled {
		opacity: 0.35;
		cursor: default;
	}
	.ebtn.remove {
		color: var(--warn-ink);
	}
	.foot {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 4px;
		flex-wrap: wrap;
	}
	.add svg,
	.sortbtn svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2.1;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.add,
	.edit {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 36px;
		padding: 0 14px;
		border: 0;
		border-radius: 999px;
		background: var(--surface-2);
		font-size: 0.84rem;
		font-weight: 600;
		color: var(--text);
		cursor: pointer;
	}
	.add:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.edit {
		margin-left: auto;
		background: transparent;
		color: var(--text-2);
	}
	.edit[aria-pressed='true'] {
		background: var(--sel);
		box-shadow: var(--sel-shadow);
		color: var(--text);
	}
	.full {
		font-size: 0.76rem;
		visibility: hidden;
	}
	.full.shown {
		visibility: visible;
	}
</style>
