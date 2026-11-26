<!--
  Recent photos from field reports around the location, by day, newest first: NWAC's
  observations (forecasters' and the public's, read from its observations page) and
  Avalanche Canada's Mountain Information Network. First those near the location (within
  20 km, and closer to it than to any other location), then, folded, those elsewhere in
  its avalanche zone. Each report's title, who sent it, when and how far away, then its
  photos. A photo opens the full-screen viewer, which flips through them all; the title
  opens the full report on the center's site. Public reports aren't checked by anyone.
-->
<script lang="ts">
	import { pushState } from '$app/navigation';
	import { page } from '$app/state';
	import { safeHref, safeImage } from '../links';
	import type { NearbyOut, NearbyReport } from '../types.gen';
	import type { UnitSystem } from '../units';
	import { byDay, reportFrom, type CenterObservations, type ViewerPhoto } from '../webcams';
	import PhotoViewer from './PhotoViewer.svelte';

	interface Props {
		/** Field reports around the location; null until they load (or if they fail). */
		data: NearbyOut | null;
		units: UnitSystem;
		tz?: string | null;
		/** The location's name, for "Near Crystal Mountain". */
		name?: string;
		/** The location's avalanche center's own observations page, linked. */
		center?: CenterObservations | null;
	}

	let { data, units, tz, name = 'this location', center = null }: Props = $props();
	type Days = { date: string; label: string; items: NearbyReport[] }[];

	const reports = $derived(data?.photo_reports ?? []);
	// Reports from before the server grouped them count as near.
	const near = $derived(reports.filter((r) => r.group !== 'zone'));
	const zone = $derived(reports.filter((r) => r.group === 'zone'));
	const nearDays = $derived(byDay(near, (r) => r.report.time, tz));
	const zoneDays = $derived(byDay(zone, (r) => r.report.time, tz));
	const zoneName = $derived(data?.zone_name || 'the avalanche zone');

	// Every photo shown, in page order (near first), for the viewer to flip through.
	const flat = $derived(
		[...nearDays, ...zoneDays].flatMap((d) =>
			d.items.flatMap((r) =>
				(r.report.photos ?? [])
					.filter((ph) => safeImage(ph.thumb) && safeImage(ph.url))
					.map((photo): ViewerPhoto => ({ photo, report: r.report, distance_km: r.distance_km }))
			)
		)
	);
	const indexOf = $derived(new Map(flat.map((p, i) => [p.photo.url + '\n' + p.report.id, i])));

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
	const nearKm = $derived(data?.near_km ?? 20);
	const span = $derived(data?.reports_days ?? 14);
	const away = (km: number) =>
		units === 'imperial' ? `${(km * 0.621371).toFixed(0)} mi` : `${km.toFixed(0)} km`;
	const clock = (iso: string) =>
		new Date(iso).toLocaleTimeString('en-US', {
			timeZone: tz ?? undefined,
			hour: 'numeric',
			minute: '2-digit'
		});

	// The viewer: a history entry of its own, so the phone's Back button closes it rather
	// than leaving the page.
	let viewing = $state<number | null>(null);
	function view(i: number, e?: MouseEvent) {
		// Ctrl/⌘-click and middle-click still open the photo in a new tab.
		if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0)) return;
		e?.preventDefault();
		viewing = i;
		if (!page.state.photo) pushState('', { photo: true });
	}
	function close() {
		if (page.state.photo) history.back();
		else viewing = null;
	}
	$effect(() => {
		if (!page.state.photo) viewing = null;
	});
</script>

{#snippet days(list: Days)}
	{#each list as day (day.date)}
		<h4>{day.label}</h4>
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
						{@const at = indexOf.get(ph.url + '\n' + r.report.id)}
						{#if at !== undefined && safeHref(ph.url)}
							<figure>
								<!-- External image: resolve() is only for routes in this app. -->
								<!-- eslint-disable svelte/no-navigation-without-resolve -->
								<a
									href={safeHref(ph.url)}
									target="_blank"
									rel="noopener noreferrer"
									aria-haspopup="dialog"
									onclick={(e) => view(at, e)}
								>
									<img
										src={safeImage(ph.thumb)}
										alt={ph.caption || `Photo from “${r.report.title || 'a field report'}”`}
										loading="lazy"
										referrerpolicy="no-referrer"
									/>
								</a>
								<!-- eslint-enable svelte/no-navigation-without-resolve -->
								{#if ph.caption}<figcaption class="small">{ph.caption}</figcaption>{/if}
							</figure>
						{/if}
					{/each}
				</div>
			</div>
		{/each}
	{/each}
{/snippet}

<section class="card photos">
	<div class="head">
		<div class="top">
			<h2>Recent field photos</h2>
			{#if flat.length}
				<button type="button" class="btn small" aria-haspopup="dialog" onclick={() => view(0)}
					>View all {flat.length} full screen</button
				>
			{/if}
		</div>
		<p class="faint small">
			From {sources}, last {span} days. What people saw; public reports aren't checked by anyone.
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
	{#if data}
		<h3>Near {name}</h3>
		{#if near.length}
			{@render days(nearDays)}
		{:else}
			<p class="muted small">
				No photos within {away(nearKm)} of {name} in the last {span} days.
			</p>
		{/if}
		{#if zone.length}
			<details class="zone" open={!near.length}>
				<summary
					>More in {zoneName}
					<span class="faint small"
						>({zone.length} report{zone.length > 1 ? 's' : ''}, closer to other places)</span
					></summary
				>
				{@render days(zoneDays)}
			</details>
		{/if}
	{/if}
</section>

{#if viewing !== null && flat.length}
	<PhotoViewer photos={flat} bind:index={viewing} {units} {tz} onclose={close} />
{/if}

<style>
	.photos {
		margin-top: 16px;
	}
	.top {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 6px 12px;
		margin: 0 0 2px;
	}
	.head h2 {
		margin: 0;
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
		margin: 18px 0 4px;
		font-size: 1rem;
	}
	h4 {
		margin: 14px 0 8px;
		font-size: 0.9rem;
		color: var(--text-2);
	}
	.zone {
		margin-top: 18px;
		border-top: 1px solid var(--panel-rim);
		padding-top: 12px;
	}
	.zone summary {
		cursor: pointer;
		font-weight: 600;
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
	figure a {
		cursor: zoom-in;
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
