<!-- The details of one period: a bottom sheet on phones, a side panel on desktop. -->
<script lang="ts">
	import { modal } from '../modal';
	import { getMeta } from '../api';
	import type { DayOut, PeriodOut } from '../types.gen';
	import { elevation, snow, speed, temperature, water, type UnitSystem } from '../units';
	import { MODEL_NAMES } from '../models';
	import { reasonText } from '../conditions';
	import RatingChip from '../components/RatingChip.svelte';

	interface Props {
		period: PeriodOut;
		bandLabel: string;
		units: UnitSystem;
		/** The ski-day rating for a resort's day period. */
		day?: DayOut | null;
		/** The snapshot's depth_method: what snow_cm (and every other depth) means. */
		depthMethod?: string;
		onclose: () => void;
	}

	let { period: p, bandLabel, units, day = null, depthMethod = 'slr', onclose }: Props = $props();
	// Open-Meteo's own snowfall ratio, from the server (0.7 cm/mm is 7:1).
	let modelRatio = $state(7);
	$effect(() => {
		getMeta()
			.then((m) => (modelRatio = Math.round(m.snowfall_cm_per_mm * 10)))
			.catch(() => {}); // keep the usual 7:1
	});
	const bySlr = $derived(depthMethod === 'slr');
	// The ratio the big number uses: the period's own, or the model's when it uses 7:1
	// (or nothing snowed enough to set a ratio).
	const shownRatio = $derived(bySlr && p.slr ? p.slr : modelRatio);
	// The other way of turning the same snow water into depth, for the details.
	const other = $derived(bySlr ? p.snow_cm_raw : p.snow_cm_slr);

	const basis = $derived(
		p.basis === 'ensemble'
			? 'Ensemble mean (too few models run this far)'
			: `Median of ${p.nmodels} models`
	);
</script>

<div class="modal" use:modal={{ onclose }}>
	<div class="scrim" role="presentation" onclick={onclose}></div>
	<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title" tabindex="-1">
		<header>
			<div>
				<h3 id="sheet-title">{p.label}</h3>
				<div class="muted">{bandLabel} · {p.hours} h · {basis}</div>
			</div>
			<button class="close" onclick={onclose} aria-label="Close">✕</button>
		</header>

		<div class="big num">{snow(p.snow_cm, units)}</div>
		<div class="muted">
			{#if p.snow_cm}at {shownRatio}:1 ·{/if}
			{p.quality ?? 'no snow'}
		</div>
		{#if day?.rating}
			<div class="rated">
				<RatingChip rating={day.rating} score={day.score} />
				<span class="muted">{(day.reasons ?? []).map((r) => reasonText(r, units)).join(' · ')}</span
				>
			</div>
		{/if}

		<dl>
			{#if other !== null && other !== p.snow_cm}
				<dt>
					{bySlr
						? `Model snowfall at ${modelRatio}:1`
						: `With the snow ratio${p.slr ? ` (${p.slr}:1)` : ''}`}
				</dt>
				<dd class="num">{snow(other, units)}</dd>
			{/if}
			<dt>Ensemble 10–90%</dt>
			<dd class="num">
				{p.ens ? `${snow(p.ens.p10, units)} – ${snow(p.ens.p90, units)}` : '–'}{p.ens?.estimated
					? ' (est.)'
					: ''}
			</dd>
			<dt>Type</dt>
			<dd>{p.ptype}</dd>
			<dt>Water / rain</dt>
			<dd class="num">{water(p.water_mm, units)} / {water(p.rain_mm, units)}</dd>
			<dt>High / low</dt>
			<dd class="num">{temperature(p.tmax_c, units)} / {temperature(p.tmin_c, units)}</dd>
			<dt>Lowest snow level</dt>
			<dd class="num">{elevation(p.snow_level_min_m, units)}</dd>
			<dt>Wind / gusts</dt>
			<dd class="num">{speed(p.wind_max_kmh, units)} / {speed(p.gust_max_kmh, units)}</dd>
			<dt>Cloud / chance of precip</dt>
			<dd class="num">{p.cloud_mean ?? '–'}% / {p.pop_max ?? '–'}%</dd>
		</dl>

		<h4>Each model</h4>
		<table class="data">
			<tbody>
				{#each Object.entries(p.models) as [m, v] (m)}
					<tr><td>{MODEL_NAMES[m] ?? m}</td><td>{v === null ? 'ended' : snow(v, units)}</td></tr>
				{/each}
				{#if p.blend_cm !== null}
					<tr><td>High-resolution models</td><td>{snow(p.blend_cm, units)}</td></tr>
				{/if}
			</tbody>
		</table>
		<p class="faint note">
			{#if bySlr}
				Snow depth is the snow water times a ratio from the temperature while it snows: 8:1 near
				freezing up to 17:1 in the cold, so colder, drier snow piles up deeper.
			{:else}
				Model snowfall uses a fixed {modelRatio}:1 snow-to-water ratio; colder, drier snow piles up
				deeper.
			{/if}
		</p>
	</div>
</div>

<style>
	.modal {
		display: contents;
	}
	.rated {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		margin-top: 6px;
		font-size: 0.85rem;
	}
	.scrim {
		position: fixed;
		inset: 0;
		background: rgb(0 0 0 / 0.35);
		z-index: 40;
	}
	.sheet {
		position: fixed;
		z-index: 41;
		background: var(--surface);
		color: var(--text);
		border: 1px solid var(--border);
		padding: 16px 18px 22px;
		overflow-y: auto;
		left: 0;
		right: 0;
		bottom: 0;
		max-height: 82vh;
		border-radius: 16px 16px 0 0;
		box-shadow: 0 -8px 30px rgb(0 0 0 / 0.2);
	}
	@media (min-width: 768px) {
		.sheet {
			left: auto;
			top: 0;
			bottom: 0;
			width: 380px;
			max-height: none;
			border-radius: 0;
		}
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 12px;
	}
	h3 {
		margin: 0;
		font-size: 1.15rem;
	}
	h4 {
		margin: 16px 0 6px;
		font-size: 0.85rem;
		color: var(--text-2);
	}
	.close {
		border: 1px solid var(--border);
		background: var(--surface-2);
		border-radius: 999px;
		width: 34px;
		height: 34px;
		cursor: pointer;
	}
	.big {
		font-size: 2.2rem;
		font-weight: 600;
		margin: 10px 0 0;
	}
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 6px 14px;
		margin: 14px 0 0;
		font-size: 0.9rem;
	}
	dt {
		color: var(--text-2);
	}
	dd {
		margin: 0;
		text-align: right;
	}
	.note {
		font-size: 0.78rem;
		margin: 10px 0 0;
	}
</style>
