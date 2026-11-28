<!--
  The models' snow on the ground at mid (a self-hosted server's `snow_depth`): the only
  depth there is for a spot, and a line beside the station's depth where there is one.
  Model snow depth is a rough guide: models melt and settle snow their own way.
-->
<script lang="ts">
	import type { Snapshot } from '../types.gen';
	import { MODEL_NAMES } from '../models';
	import { monthDay } from '../time';
	import { elevation, snow, type UnitSystem } from '../units';

	let { snap, units }: { snap: Snapshot; units: UnitSystem } = $props();
	const pack = $derived(snap.snowpack ?? null);
	const station = $derived(
		new Map((snap.snotel?.daily ?? []).map((d) => [d.date, d.depth_cm] as const))
	);
	const today = $derived(snap.now.slice(0, 10));
	const rows = $derived(
		pack
			? pack.dates.map((d, i) => ({
					date: d,
					model: pack.depth_cm[i],
					station: station.get(d) ?? null,
					past: d <= today
				}))
			: []
	);
	const hasStation = $derived(rows.some((r) => r.station !== null));
	// A small line chart: model depth solid, station dots.
	const W = 300;
	const H = 80;
	const top = $derived(Math.max(1, ...rows.flatMap((r) => [r.model ?? 0, r.station ?? 0])) * 1.1);
	const x = (i: number) => (rows.length > 1 ? (i / (rows.length - 1)) * W : W / 2);
	const y = (v: number) => H - (v / top) * H;
	const line = $derived(
		rows
			.map((r, i) => (r.model === null ? null : `${x(i).toFixed(1)} ${y(r.model).toFixed(1)}`))
			.filter((p): p is string => p !== null)
			.map((p, i) => `${i ? 'L' : 'M'}${p}`)
			.join('')
	);
</script>

{#if pack}
	<section class="card">
		<h2>Model snowpack</h2>
		<p class="muted small">
			The models' snow on the ground at {elevation(pack.elev_m, units)}: {snow(pack.now_cm, units)}
			now. A rough guide: each model melts and settles snow its own way{hasStation
				? '; dots are the station'
				: ''}.
		</p>
		<svg viewBox="-4 -4 {W + 8} {H + 8}" role="img" aria-label="Model snow depth by day">
			<path d={line} class="model" />
			{#each rows as r, i (r.date)}
				{#if r.station !== null}<circle cx={x(i)} cy={y(r.station)} r="3" class="stn" />{/if}
			{/each}
		</svg>
		<div class="axis faint small">
			<span>{rows[0] ? monthDay(rows[0].date) : ''}</span>
			<span>{rows.length ? monthDay(rows[rows.length - 1].date) : ''}</span>
		</div>
		<table class="data small">
			<tbody>
				{#each Object.entries(pack.models) as [m, v] (m)}
					<tr><td>{MODEL_NAMES[m] ?? m}</td><td class="num">{snow(v, units)}</td></tr>
				{/each}
			</tbody>
		</table>
	</section>
{/if}

<style>
	.small {
		font-size: 0.85rem;
	}
	svg {
		width: 100%;
		height: auto;
		display: block;
		margin-top: 8px;
	}
	.model {
		fill: none;
		stroke: var(--accent);
		stroke-width: 2;
	}
	.stn {
		fill: var(--text-2);
	}
	.axis {
		display: flex;
		justify-content: space-between;
	}
</style>
