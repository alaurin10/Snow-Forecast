<!--
  Recent photos from field reports near the location (Avalanche Canada's Mountain
  Information Network), by day, newest first: each report's title, when and how far
  away, then its photos. A photo opens large; the title opens the full report. What
  people saw and chose to share, not checked by anyone.
-->
<script lang="ts">
	import { safeHref, safeImage } from '../links';
	import type { NearbyOut } from '../types.gen';
	import type { UnitSystem } from '../units';
	import { byDay } from '../webcams';

	interface Props {
		data: NearbyOut;
		units: UnitSystem;
		tz?: string | null;
	}

	let { data, units, tz }: Props = $props();

	const days = $derived(byDay(data.photo_reports ?? [], (r) => r.report.time, tz));
	const away = (km: number) =>
		units === 'imperial' ? `${(km * 0.621371).toFixed(0)} mi` : `${km.toFixed(0)} km`;
	const clock = (iso: string) =>
		new Date(iso).toLocaleTimeString('en-US', {
			timeZone: tz ?? undefined,
			hour: 'numeric',
			minute: '2-digit'
		});
</script>

<section class="card photos">
	<div class="head">
		<h2>Recent field photos</h2>
		<p class="faint small">
			From people's reports to Avalanche Canada's Mountain Information Network within {away(
				data.radius_km
			)}, last {data.reports_days ?? 14} days. What they saw; not checked by anyone.
		</p>
	</div>
	{#if days.length}
		{#each days as day (day.date)}
			<h3>{day.label}</h3>
			{#each day.items as r (r.report.id)}
				<div class="report">
					<p class="title">
						{#if safeHref(r.report.url)}
							<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
							<a href={safeHref(r.report.url)} target="_blank" rel="noopener noreferrer"
								>{r.report.title || 'Field report'}</a
							>
						{:else}
							<strong>{r.report.title || 'Field report'}</strong>
						{/if}
						<span class="faint small"
							>{clock(r.report.time)} · {away(r.distance_km)} away{r.report.region
								? ` · ${r.report.region}`
								: ''}</span
						>
					</p>
					<div class="grid">
						{#each r.report.photos ?? [] as ph, i (i)}
							{#if safeImage(ph.thumb) && safeHref(ph.url)}
								<figure>
									<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
									<a href={safeHref(ph.url)} target="_blank" rel="noopener noreferrer">
										<img
											src={safeImage(ph.thumb)}
											alt={ph.caption || `Photo from “${r.report.title || 'a field report'}”`}
											loading="lazy"
											referrerpolicy="no-referrer"
										/>
									</a>
									{#if ph.caption}<figcaption class="small">{ph.caption}</figcaption>{/if}
								</figure>
							{/if}
						{/each}
					</div>
				</div>
			{/each}
		{/each}
	{:else}
		<p class="muted small">
			No photos in reports within {away(data.radius_km)} in the last {data.reports_days ?? 14}
			days.
		</p>
	{/if}
</section>

<style>
	.photos {
		margin-top: 16px;
	}
	.head h2 {
		margin: 0 0 2px;
	}
	.head p {
		margin: 0 0 4px;
	}
	h3 {
		margin: 18px 0 8px;
		font-size: 0.95rem;
	}
	.report + .report {
		margin-top: 14px;
	}
	.title {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 2px 10px;
		margin: 0 0 6px;
	}
	.grid {
		display: grid;
		gap: 8px;
		grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
	}
	figure {
		margin: 0;
		display: grid;
		gap: 4px;
		align-content: start;
	}
	img {
		display: block;
		width: 100%;
		aspect-ratio: 4 / 3;
		object-fit: cover;
		border-radius: 8px;
		background: var(--surface-2);
	}
	figcaption {
		color: var(--text-2);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
</style>
