<!--
  Recent photos from field reports near the location, by day, newest first: NWAC's
  observations (forecasters' and the public's, read from its observations page) and
  Avalanche Canada's Mountain Information Network. Each report's title, who sent it, when
  and how far away, then its photos. A photo opens large; the title opens the full
  report on the center's site. Public reports are what people saw, not checked.
-->
<script lang="ts">
	import { safeHref, safeImage } from '../links';
	import type { NearbyOut } from '../types.gen';
	import type { UnitSystem } from '../units';
	import { byDay, reportFrom, type CenterObservations } from '../webcams';

	interface Props {
		/** Field reports around the location; null until they load (or if they fail). */
		data: NearbyOut | null;
		units: UnitSystem;
		tz?: string | null;
		/** The location's avalanche center's own observations page, linked. */
		center?: CenterObservations | null;
	}

	let { data, units, tz, center = null }: Props = $props();

	const reports = $derived(data?.photo_reports ?? []);
	const days = $derived(byDay(reports, (r) => r.report.time, tz));
	// Whose reports these are, for the line under the heading.
	const fromNwac = $derived(!!center?.shown || reports.some((r) => r.report.source === 'nwac'));
	const fromMin = $derived(reports.some((r) => r.report.source !== 'nwac') || !fromNwac);
	const sources = $derived(
		[
			fromNwac ? 'NWAC observations (forecasters and the public)' : '',
			fromMin ? 'people’s reports to Avalanche Canada’s Mountain Information Network' : ''
		]
			.filter(Boolean)
			.join(' and ')
	);
	const radius = $derived(data?.radius_km ?? 60);
	const span = $derived(data?.reports_days ?? 14);
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
			From {sources} within {away(radius)}, last {span} days. What people saw; public reports aren't checked
			by anyone.
		</p>
		{#if center && safeHref(center.url)}
			<p class="center">
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<a class="btn small" href={safeHref(center.url)} target="_blank" rel="noopener noreferrer"
					>{center.shown ? `All ${center.name} observations` : `Recent ${center.name} observations`}
					↗</a
				>
				<span class="faint small"
					>{center.shown
						? `Each report opens in full on ${center.name}'s site.`
						: `${center.name}'s photos and reports open on its own site; they can't be shown here.`}</span
				>
			</p>
		{/if}
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
							>{reportFrom(r.report)} · {r.report.day ? '' : `${clock(r.report.time)} · `}{away(
								r.distance_km
							)} away{r.report.region ? ` · ${r.report.region}` : ''}</span
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
	{:else if data}
		<p class="muted small">
			No photos in {fromNwac && fromMin
				? 'field reports'
				: fromNwac
					? 'NWAC observations'
					: 'Avalanche Canada reports'} within {away(radius)} in the last {span} days.
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
	.center {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 10px;
		margin: 10px 0 4px;
	}
	.center .btn {
		text-decoration: none;
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
