<!--
  The Confidence tab: how sure is this forecast? Top to bottom: a plain answer for each
  window (the total, its likely range, where each model stands), the models day by day,
  the chance of each amount, how the forecast has moved over the last runs, and how it
  has done against the snow station.
-->
<script lang="ts">
	import type { BandOut, Snapshot, TrendOut, VerificationOut } from '../types.gen';
	import type { LoadState } from '../load';
	import { confidenceNote, dayReads, trendRead, windowRead, type WindowRead } from '../confidence';
	import { MODEL_NAMES, modelColor } from '../models';
	import { elevation, snow, snowNum, converters, type UnitSystem } from '../units';
	import ModelAgreement from '../charts/ModelAgreement.svelte';
	import ModelDays from '../charts/ModelDays.svelte';
	import TrendChart from '../charts/TrendChart.svelte';
	import TrendDays from '../components/TrendDays.svelte';
	import ConfidenceMeter from './ConfidenceMeter.svelte';
	import WindowRange from './WindowRange.svelte';
	import ModelTable from './ModelTable.svelte';
	import ChanceLadder from './ChanceLadder.svelte';
	import TrackRecord from './TrackRecord.svelte';

	interface Props {
		snap: Snapshot;
		/** The elevation chosen on the page. */
		band: BandOut;
		trend: TrendOut | null;
		scores: VerificationOut | null;
		scoresLoad?: LoadState;
		units: UnitSystem;
		/** Fixed chart width (tests); otherwise each chart measures its container. */
		width?: number;
	}

	let { snap, band, trend, scores, scoresLoad = 'ready', units, width }: Props = $props();
	const c = $derived(converters(units));
	const mid = $derived(snap.bands[1]);
	const reads = $derived<WindowRead[]>([windowRead(band, 'next5'), windowRead(band, 'd6_10')]);
	// Both windows on one scale, so their ranges compare by eye.
	const top = $derived(
		Math.max(1, ...reads.flatMap((r) => [r.snow_cm ?? 0, r.hi ?? 0, ...r.models.map((m) => m.cm)]))
	);
	const days = $derived(dayReads(snap.daily));
	const moved = $derived(trendRead(trend?.runs ?? []));
	const since = (iso: string) =>
		new Date(iso).toLocaleString('en-US', { weekday: 'short', hour: 'numeric' });
	const movedText = $derived.by(() => {
		if (!moved) return null;
		const span = moved.days === 1 ? 'the day both cover' : `the ${moved.days} days both cover`;
		const back = `${moved.runs_back} run${moved.runs_back === 1 ? '' : 's'} ago (${since(moved.since)})`;
		if (moved.direction === 'steady') return `Holding steady since ${back}, over ${span}.`;
		return `${moved.direction === 'up' ? 'Up' : 'Down'} ${snow(Math.abs(moved.change_cm), units)} since ${back}, over ${span}.`;
	});
	// Ensemble members are fetched at mid; other elevations scale them.
	const membersFor = (name: 'next5' | 'd6_10'): number[] => {
		const m = mid.windows[name]?.members_cm ?? [];
		const scale = band.band === 'mid' ? 1 : (band.windows[name]?.scale ?? null);
		return scale === null ? [] : m.map((v) => v * scale);
	};
	let view = $state<'days' | 'total'>('days');
	const basisNote = (r: WindowRead) =>
		r.basis === 'ensemble'
			? `likely${r.estimated ? ' (est.)' : ''}`
			: r.basis === 'models'
				? 'across the models'
				: '';
</script>

<div class="stackcol">
	<section class="card" aria-labelledby="conf-h">
		<h2 id="conf-h">How sure is this forecast?</h2>
		<div class="reads">
			{#each reads as r (r.key)}
				<div class="read">
					<div class="rhead">
						<span class="eyebrow">{r.label}</span>
						<ConfidenceMeter level={r.confidence} />
					</div>
					<div class="rnum">
						<span class="big num">{snowNum(r.snow_cm, units)}<small>{c.snowUnit}</small></span>
						{#if r.lo !== null && r.hi !== null}
							<span class="muted likely"
								>{snowNum(r.lo, units)}–{snowNum(r.hi, units)} {c.snowUnit} {basisNote(r)}</span
							>
						{/if}
					</div>
					<WindowRange read={r} max={top} {units} {width} />
					{#if r.models.length}
						<ul class="mlist">
							{#each r.models as m (m.model)}
								<li>
									<i class="key" style="background: {modelColor(m.model)}"></i>{MODEL_NAMES[
										m.model
									] ?? m.model}
									<span class="num">{snowNum(m.cm, units)}</span>
								</li>
							{/each}
						</ul>
					{/if}
					<p class="note">{confidenceNote(r)}</p>
				</div>
			{/each}
		</div>
		<p class="faint small foot">
			At {band.label} ({elevation(band.elev_m, units)}). The band is where 80% of ensemble members
			land, the tick is the app’s forecast, each dot a model that reaches the whole window.
		</p>
	</section>

	<section class="card" aria-labelledby="models-h">
		<div class="cardhead">
			<h2 id="models-h">The models, day by day</h2>
			<div class="seg" role="group" aria-label="Chart">
				<button aria-pressed={view === 'days'} onclick={() => (view = 'days')}>Each day</button>
				<button aria-pressed={view === 'total'} onclick={() => (view = 'total')}
					>Running total</button
				>
			</div>
		</div>
		{#if view === 'days'}
			<ModelDays {days} models={snap.models} {units} {width} />
		{:else}
			<ModelAgreement daily={snap.daily} models={snap.models} {units} {width} />
		{/if}
		<ModelTable {days} models={snap.models} {units} />
		<p class="faint small foot">
			At {mid.label} ({elevation(mid.elev_m, units)}), midnight to midnight, so a day here can
			differ a little from the Forecast tab’s 6 AM to 6 AM days. A model’s line ends where its run
			does.
		</p>
	</section>

	<div class="two">
		<section class="card">
			<ChanceLadder
				next5={membersFor('next5')}
				d6_10={membersFor('d6_10')}
				{units}
				estimated={band.band !== 'mid'}
			/>
		</section>
		<section class="card">
			<h2>How the forecast has changed</h2>
			{#if movedText}<p class="lede">{movedText}</p>{/if}
			<TrendChart runs={trend?.runs ?? []} {units} {width} />
			<TrendDays runs={trend?.runs ?? []} {units} />
		</section>
	</div>

	<section class="card">
		<TrackRecord data={scores} {units} load={scoresLoad} />
	</section>
</div>

<style>
	.stackcol {
		display: grid;
		gap: 16px;
	}
	h2 {
		margin: 0 0 10px;
	}
	.reads {
		display: grid;
		gap: 18px 28px;
	}
	.two {
		display: grid;
		gap: 16px;
		align-items: start;
	}
	@media (min-width: 768px) {
		.reads,
		.two {
			grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		}
		.read + .read {
			padding-left: 28px;
			border-left: 1px solid var(--grid);
		}
	}
	.read {
		display: grid;
		gap: 6px;
		align-content: start;
		min-width: 0;
	}
	.rhead {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 4px 10px;
	}
	.rnum {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 2px 12px;
	}
	.big {
		font-family: var(--font-num);
		font-size: 1.9rem;
		font-weight: 600;
		line-height: 1.1;
		letter-spacing: -0.03em;
	}
	.big small {
		font-family: var(--font-ui);
		font-size: 0.82rem;
		font-weight: 500;
		letter-spacing: 0;
		margin-left: 3px;
		color: var(--text-2);
	}
	.likely {
		font-size: 0.86rem;
	}
	.mlist {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 14px;
		margin: 0;
		padding: 0;
		list-style: none;
		font-size: 0.8rem;
		color: var(--text-2);
	}
	.mlist .num {
		color: var(--text);
		font-weight: 600;
		margin-left: 3px;
	}
	.key {
		display: inline-block;
		width: 9px;
		height: 9px;
		border-radius: 50%;
		margin-right: 5px;
	}
	.note {
		margin: 2px 0 0;
		font-size: 0.9rem;
	}
	.small {
		font-size: 0.8rem;
	}
	.foot {
		margin: 12px 0 0;
	}
	.lede {
		margin: 0 0 8px;
		font-size: 0.9rem;
	}
	.cardhead {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 8px 12px;
		margin-bottom: 10px;
	}
	.cardhead h2 {
		margin: 0;
	}
	@media (max-width: 640px) {
		.stackcol {
			gap: 12px;
		}
	}
</style>
