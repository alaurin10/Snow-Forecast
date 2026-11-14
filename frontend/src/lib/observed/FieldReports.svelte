<!--
  Recent field reports near the location from Avalanche Canada's Mountain Information
  Network: what people in the mountains saw and chose to share, newest first, each
  linking to the full report. Not checked by anyone.
-->
<script lang="ts">
	import { safeHref } from '../links';
	import type { NearbyOut } from '../types.gen';
	import { REPORT_KINDS } from '../map/features';
	import { ago } from '../time';
	import type { UnitSystem } from '../units';

	interface Props {
		data: NearbyOut;
		units: UnitSystem;
	}

	let { data, units }: Props = $props();
	const away = (km: number) =>
		units === 'imperial' ? `${(km * 0.621371).toFixed(0)} mi` : `${km.toFixed(0)} km`;
</script>

<section class="card">
	<h2>Field reports nearby</h2>
	{#if data.reports.length}
		<ul class="reports">
			{#each data.reports as r (r.report.id)}
				<li>
					<span class="main">
						{#if safeHref(r.report.url)}
							<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
							<a href={safeHref(r.report.url)} target="_blank" rel="noopener noreferrer"
								>{r.report.title || 'Field report'}</a
							>
						{:else}
							<strong>{r.report.title || 'Field report'}</strong>
						{/if}
						<span class="faint meta"
							>{ago(r.report.time)} · {away(r.distance_km)} away{r.report.region
								? ` · ${r.report.region}`
								: ''}{r.report.images
								? ` · ${r.report.images} photo${r.report.images > 1 ? 's' : ''}`
								: ''}</span
						>
					</span>
					<span class="kinds">
						{#each r.report.kinds as k (k)}
							<span class="kind"
								><i style:background={REPORT_KINDS[k]?.color}></i>{REPORT_KINDS[k]?.label ??
									k}</span
							>
						{/each}
					</span>
				</li>
			{/each}
		</ul>
	{:else}
		<p class="muted small">
			No reports within {away(data.radius_km)} in the last {data.reports_days ?? 14} days.
		</p>
	{/if}
	<p class="faint small">
		From Avalanche Canada’s Mountain Information Network: what someone saw and chose to share, not
		checked.
	</p>
</section>

<style>
	h2 {
		margin: 0 0 6px;
	}
	.small {
		font-size: 0.82rem;
	}
	.reports {
		margin: 0 0 10px;
		padding: 0;
		list-style: none;
		display: grid;
	}
	.reports li {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 4px 14px;
		padding: 9px 0;
		border-top: 1px solid var(--grid);
		font-size: 0.9rem;
	}
	.reports li:first-child {
		border-top: 0;
		padding-top: 2px;
	}
	.main {
		display: grid;
		min-width: 0;
	}
	.main a {
		color: var(--text);
		font-weight: 600;
	}
	.meta {
		font-size: 0.78rem;
	}
	.kinds {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 10px;
		font-size: 0.78rem;
		color: var(--text-2);
	}
	.kind i {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		margin-right: 5px;
	}
</style>
