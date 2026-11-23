<!-- Compare: one row per location in the comparison, day by day. The name is the chart's
     legend and its switch: tap it to draw or hide the location's line (a filled swatch in
     the line's colour when drawn, an empty ring when not). Ten day cells follow, at the
     chosen band (the Calendar's cells for snow, the day's figure for the other metrics),
     then a summary of the days the chart shows. Cells outside those days are faded; drag
     or tap the days to move the chart. Phones put the name above a full-width row of
     cells, as the Calendar does. Edit removes and reorders. -->
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
		cells: DayCell[];
		summary: Summary | null;
		/** "updated 9 h ago" for an old forecast, else null. */
		stale: string | null;
	}
</script>

<script lang="ts">
	import { bucket } from '../calendar';
	import { rainyDay, type CompareMetric } from '../compare';
	import {
		converters,
		elevation,
		snow,
		snowNum,
		speed,
		temperature,
		type UnitSystem
	} from '../units';
	import { monthDay, weekday } from '../time';
	import { viewport } from '../viewport.svelte';

	interface Props {
		rows: RowView[];
		dates: string[];
		metric: CompareMetric;
		units: UnitSystem;
		/** The days the chart shows (indexes into `dates`). */
		inView: { from: number; to: number };
		/** The chart shows every day: nothing to move. */
		whole: boolean;
		canPrev: boolean;
		canNext: boolean;
		sort: 'mine' | 'snow';
		/** The comparison holds as many locations as it can. */
		full: boolean;
		editing?: boolean;
		onsort: () => void;
		ontoggle: (id: string) => void;
		onremove: (id: string) => void;
		onmove: (id: string, by: -1 | 1) => void;
		onadd: () => void;
		/** Centre the chart on day `k`. */
		onday: (k: number) => void;
		/** Move the chart a day earlier (-1) or later (1). */
		onstep: (by: -1 | 1) => void;
	}

	let {
		rows,
		dates,
		metric,
		units,
		inView,
		whole,
		canPrev,
		canNext,
		sort,
		full,
		editing = $bindable(false),
		onsort,
		ontoggle,
		onremove,
		onmove,
		onadd,
		onday,
		onstep
	}: Props = $props();

	const phone = $derived(viewport.phone);
	const c = $derived(converters(units));
	const n = $derived(Math.max(1, dates.length));
	const isIn = (k: number) => whole || (k >= inView.from && k <= inView.to);
	const dayName = (d: string) => `${weekday(d)} ${monthDay(d)}`;
	const days = $derived(
		dates.map((d, k) => {
			const wd = weekday(d);
			return {
				date: d,
				label: k === 0 ? (phone ? 'Tod' : 'Today') : phone ? wd.slice(0, 2) : wd,
				num: String(Number(d.slice(8))),
				weekend: wd === 'Sat' || wd === 'Sun'
			};
		})
	);

	const round = (v: number | null) => (v === null ? null : Math.round(v));
	const thousands = (m: number | null) => {
		const v = c.height(m);
		return v === null ? '–' : `${(v / 1000).toFixed(1)}k`;
	};
	/** A day cell: its class, its text and what a screen reader hears. */
	function cell(d: DayCell): { cls: string; text: string; label: string } {
		const day = dayName(d.date);
		if (!d.has) return { cls: 'heat b0', text: '', label: `${day}: no forecast` };
		if (metric === 'snow') {
			const rainy = rainyDay(d);
			return {
				cls: `heat b${bucket(d.snow)}${rainy ? ' rainy' : ''}`,
				text: Number(snowNum(d.snow, units)) > 0 ? snowNum(d.snow, units) : '',
				label: `${day}: ${snow(d.snow, units)}${rainy ? ', rain' : ''}`
			};
		}
		if (metric === 'temp') {
			const hi = round(c.temp(d.tmax));
			return {
				cls: 'heat b0 val',
				text: hi === null ? '–' : `${hi}°`,
				label: `${day}: high ${temperature(d.tmax, units)}, low ${temperature(d.tmin, units)}`
			};
		}
		if (metric === 'wind') {
			const g = round(c.speed(d.gust));
			return {
				cls: 'heat b0 val',
				text: g === null ? '–' : `${g}`,
				label: `${day}: top gust ${speed(d.gust, units)}`
			};
		}
		if (metric === 'fl')
			return {
				cls: 'heat b0 val',
				text: thousands(d.flMin),
				label: `${day}: lowest freezing level ${elevation(d.flMin, units)}`
			};
		if (metric === 'slr') {
			const r = round(d.slr);
			return {
				cls: 'heat b0 val',
				text: r === null ? '·' : phone ? `${r}` : `${r}:1`,
				label: `${day}: ${r === null ? 'no snow' : `snow ratio ${r}:1`}`
			};
		}
		const cl = round(d.cloud);
		return {
			cls: 'heat b0 val',
			text: cl === null ? '–' : phone ? `${cl}` : `${cl}%`,
			label: `${day}: cloud ${cl === null ? 'unknown' : `${cl}%`}`
		};
	}

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
	function sumText(s: Summary | null): string {
		if (!s) return '';
		if (metric === 'snow') return snowNum(s.snow, units);
		if (metric === 'temp') {
			const hi = round(c.temp(s.tmax));
			const lo = round(c.temp(s.tmin));
			return hi === null || lo === null ? '–' : `${hi}°/${lo}°`;
		}
		if (metric === 'wind') return `${round(c.speed(s.gust)) ?? '–'}`;
		if (metric === 'fl') {
			const v = c.height(s.flMin);
			return v === null ? '–' : (Math.round(v / 10) * 10).toLocaleString('en-US');
		}
		if (metric === 'slr') return s.slr === null ? '–' : `${Math.round(s.slr)}:1`;
		return s.cloud === null ? '–' : `${Math.round(s.cloud)}%`;
	}

	// Dragging or tapping across a row's cells moves the chart's window.
	let dragging = false;
	const dayAt = (e: PointerEvent) => {
		const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
		return Math.max(0, Math.min(n - 1, Math.floor(((e.clientX - r.left) / r.width) * n)));
	};
	function down(e: PointerEvent) {
		if (whole) return;
		dragging = true;
		(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
		onday(dayAt(e));
	}
	function daysKey(e: KeyboardEvent) {
		if (whole) return;
		if (e.key === 'ArrowRight' && canNext) onstep(1);
		else if (e.key === 'ArrowLeft' && canPrev) onstep(-1);
		else if (e.key === 'Home') onday(0);
		else return;
		e.preventDefault();
	}
</script>

<div class="cr" class:phone class:editing style:--n={n}>
	<div class="row head">
		<div class="name">
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
		</div>
		<div
			class="cells days"
			role="slider"
			tabindex={whole ? -1 : 0}
			aria-label="Days the chart shows"
			aria-valuemin={0}
			aria-valuemax={n - 1}
			aria-valuenow={inView.from}
			aria-valuetext={dates.length
				? `${dayName(dates[inView.from] ?? dates[0])} to ${dayName(dates[inView.to] ?? dates[0])}`
				: ''}
			onkeydown={daysKey}
		>
			{#each days as d, k (d.date)}
				<span class="day" class:in={isIn(k)} class:weekend={d.weekend}
					>{d.label}{#if !phone}<small>{d.num}</small>{/if}</span
				>
			{/each}
		</div>
		<div class="sum" title="Over the days the chart shows">{sumHead}</div>
	</div>

	<ul class="list">
		{#each rows as r (r.id)}
			<li class="row">
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
						>{#if r.elev_m !== null}{phone ? '' : `${r.bandLabel} · `}{elevation(
								r.elev_m,
								units
							)}{/if}{#if r.stale}<span class="stale">{` · ${r.stale}`}</span>{/if}</small
					>
				</div>
				{#if editing}
					<div class="cells edits">
						<button
							class="ebtn"
							onclick={() => onmove(r.id, -1)}
							aria-label="Move {r.name} up"
							disabled={rows[0]?.id === r.id}>↑</button
						>
						<button
							class="ebtn"
							onclick={() => onmove(r.id, 1)}
							aria-label="Move {r.name} down"
							disabled={rows[rows.length - 1]?.id === r.id}>↓</button
						>
						<button class="ebtn remove" onclick={() => onremove(r.id)} aria-label="Remove {r.name}"
							>Remove</button
						>
					</div>
					<div class="sum"></div>
				{:else if r.state === 'ok'}
					<!-- svelte-ignore a11y_no_static_element_interactions (the days row above is the keyboard control) -->
					<div
						class="cells"
						onpointerdown={down}
						onpointermove={(e) => dragging && onday(dayAt(e))}
						onpointerup={() => (dragging = false)}
						onpointercancel={() => (dragging = false)}
					>
						{#each r.cells as d, k (d.date)}
							{@const x = cell(d)}
							<span
								class="{x.cls} cellbox"
								class:in={isIn(k)}
								role="img"
								aria-label="{r.name}, {x.label}">{x.text}</span
							>
						{/each}
					</div>
					<div class="sum num">{sumText(r.summary)}</div>
				{:else}
					<div class="cells msg">
						{r.state === 'loading'
							? 'Loading…'
							: r.state === 'nodata'
								? 'No forecast yet'
								: 'Couldn’t load its forecast'}
					</div>
					<div class="sum"></div>
				{/if}
			</li>
		{/each}
	</ul>

	<div class="foot">
		{#if !whole}
			<button
				class="step"
				aria-label="One day earlier"
				disabled={!canPrev}
				onclick={() => onstep(-1)}
				><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
					><path d="M15 5l-7 7 7 7" /></svg
				></button
			>
			<button class="step" aria-label="One day later" disabled={!canNext} onclick={() => onstep(1)}
				><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
					><path d="M9 5l7 7-7 7" /></svg
				></button
			>
		{/if}
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
		--name-w: 210px;
		--sum-w: 96px;
	}
	.row {
		display: grid;
		grid-template-columns: var(--name-w) minmax(0, 1fr) var(--sum-w);
		grid-template-areas: 'name cells sum';
		align-items: center;
		gap: 10px;
		min-width: 0;
	}
	/* Phones: the name and the summary on one line, the cells full width under them. */
	.phone .row {
		grid-template-columns: minmax(0, 1fr) auto;
		grid-template-areas: 'name sum' 'cells cells';
		gap: 3px 10px;
	}
	.name {
		grid-area: name;
		min-width: 0;
		display: grid;
		gap: 1px;
	}
	.phone .name {
		display: flex;
		align-items: baseline;
		gap: 6px;
	}
	.cells {
		grid-area: cells;
		display: grid;
		grid-template-columns: repeat(var(--n), minmax(0, 1fr));
		gap: 3px;
		min-width: 0;
		touch-action: pan-y;
		user-select: none;
	}
	.sum {
		grid-area: sum;
		text-align: right;
		font-size: 0.86rem;
		font-weight: 600;
		white-space: nowrap;
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 8px;
	}
	.phone .list {
		gap: 10px;
	}
	.head .sum {
		font-size: 0.74rem;
		font-weight: 600;
		color: var(--text-2);
	}
	.days {
		cursor: default;
	}
	.day {
		display: grid;
		justify-items: center;
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		transition: color var(--ease);
	}
	.day.weekend {
		color: var(--accent-ink);
	}
	.day:not(.in) {
		opacity: 0.55;
	}
	.day small {
		font-size: 0.68rem;
		font-weight: 400;
	}
	.sortbtn {
		justify-self: start;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 32px;
		padding: 0 10px 0 6px;
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
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
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
		min-height: 30px;
		border-radius: 8px;
	}
	button.who:hover .lname {
		text-decoration: underline;
		text-decoration-color: var(--text-3);
		text-underline-offset: 3px;
	}
	.phone .who {
		flex: 0 1 auto;
		max-width: 70%;
		font-size: 0.86rem;
		min-height: 28px;
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
		min-width: 0;
		font-size: 0.74rem;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		padding-left: 20px;
	}
	.phone .sub {
		padding-left: 0;
		flex: 1 1 0;
	}
	.stale {
		color: var(--warn-ink);
	}
	.cellbox {
		height: 30px;
		font-size: 0.78rem;
		transition: opacity var(--ease);
	}
	.phone .cellbox {
		height: 24px;
		border-radius: 7px;
		font-size: 0.68rem;
	}
	.cellbox.val {
		font-family: var(--font-num);
		font-weight: 600;
		color: var(--text-2);
		background: var(--surface-2);
	}
	.cellbox:not(.in) {
		opacity: 0.4;
	}
	.msg {
		display: block;
		font-size: 0.8rem;
		color: var(--text-3);
		padding: 6px 0;
	}
	.edits {
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
	.step {
		display: grid;
		place-items: center;
		width: 40px;
		height: 36px;
		border: 0;
		border-radius: 12px;
		background: var(--surface-2);
		color: var(--text-2);
		cursor: pointer;
	}
	.step:disabled {
		opacity: 0.35;
		cursor: default;
	}
	.step svg,
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
	.add {
		margin-left: 4px;
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
