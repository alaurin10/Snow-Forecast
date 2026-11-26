<!--
  Recent photos from field reports around the location, for a quick look: NWAC's
  observations and Avalanche Canada's Mountain Information Network, newest first. Those
  near the location (within 20 km, and closer to it than to any other location) first;
  the rest of its avalanche zone folded below. One short line per report (place, day, how
  far), then its photos; a photo opens the full-screen viewer, which flips through them
  all (and, on wide screens, shows them all at once from Gallery). What people reported
  in words is on the Backcountry tab.
-->
<script lang="ts">
	import { safeHref, safeImage } from '../links';
	import type { NearbyOut, NearbyReport } from '../types.gen';
	import type { UnitSystem } from '../units';
	import { reportWhen, type CenterObservations, type ViewerPhoto } from '../webcams';
	import PhotoViewer from './PhotoViewer.svelte';
	import { photoViewer } from './viewer.svelte';

	interface Props {
		/** Field reports around the location; null until they load (or if they fail). */
		data: NearbyOut | null;
		units: UnitSystem;
		tz?: string | null;
		/** The location's name, for "No photos within … of Crystal Mountain". */
		name?: string;
		/** The location's avalanche center's own observations page, linked. */
		center?: CenterObservations | null;
	}

	let { data, units, tz, name = 'this location', center = null }: Props = $props();

	const reports = $derived(data?.photo_reports ?? []);
	// Reports from before the server grouped them count as near.
	const near = $derived(reports.filter((r) => r.group !== 'zone'));
	const zone = $derived(reports.filter((r) => r.group === 'zone'));
	const zoneName = $derived(data?.zone_name || 'the avalanche zone');

	const pics = (r: NearbyReport) =>
		(r.report.photos ?? []).filter((ph) => safeImage(ph.thumb) && safeImage(ph.url));
	// Every photo shown, in page order (near first), for the viewer to flip through.
	const flat = $derived(
		[...near, ...zone].flatMap((r) =>
			pics(r).map((photo): ViewerPhoto => ({ photo, report: r.report, distance_km: r.distance_km }))
		)
	);
	const indexOf = $derived(new Map(flat.map((p, i) => [p.photo.url + '\n' + p.report.id, i])));

	const fromNwac = $derived(!!center?.shown || reports.some((r) => r.report.source === 'nwac'));
	const fromMin = $derived(reports.some((r) => r.report.source !== 'nwac'));
	const source = $derived(
		fromNwac && fromMin
			? 'NWAC and Avalanche Canada field reports'
			: fromNwac
				? 'NWAC observations'
				: 'Avalanche Canada field reports'
	);
	const nearKm = $derived(data?.near_km ?? 20);
	const span = $derived(data?.reports_days ?? 14);
	const away = (km: number) =>
		units === 'imperial' ? `${(km * 0.621371).toFixed(0)} mi` : `${km.toFixed(0)} km`;

	const viewer = photoViewer();
	let gallery = $state(false);
	function open(i: number, e?: MouseEvent, all = false) {
		gallery = all;
		viewer.open(i, e);
	}
</script>

{#snippet list(items: NearbyReport[])}
	{#each items as r (r.report.id)}
		<div class="report">
			<p class="line">
				{#if safeHref(r.report.url)}
					<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
					<a href={safeHref(r.report.url)} target="_blank" rel="noopener noreferrer"
						>{r.report.title || 'Field report'}</a
					>
				{:else}
					<strong>{r.report.title || 'Field report'}</strong>
				{/if}
				<span class="faint">{reportWhen(r.report, tz)} · {away(r.distance_km)}</span>
			</p>
			<div class="grid">
				{#each pics(r) as ph, i (i)}
					{@const at = indexOf.get(ph.url + '\n' + r.report.id)}
					{#if at !== undefined}
						<!-- External image: resolve() is only for routes in this app. -->
						<!-- eslint-disable svelte/no-navigation-without-resolve -->
						<a
							href={safeHref(ph.url)}
							target="_blank"
							rel="noopener noreferrer"
							aria-haspopup="dialog"
							onclick={(e) => open(at, e)}
						>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
							<img
								src={safeImage(ph.thumb)}
								alt={ph.caption || `Photo from “${r.report.title || 'a field report'}”`}
								loading="lazy"
								referrerpolicy="no-referrer"
							/>
						</a>
					{/if}
				{/each}
			</div>
		</div>
	{/each}
{/snippet}

<section class="card photos">
	<div class="top">
		<h2>Recent field photos</h2>
		<span class="links">
			{#if flat.length > 1}
				<button
					type="button"
					class="btn small gallery"
					aria-haspopup="dialog"
					onclick={() => open(0, undefined, true)}>Gallery</button
				>
			{/if}
			{#if center && safeHref(center.url)}
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<a href={safeHref(center.url)} target="_blank" rel="noopener noreferrer"
					>{center.name} observations ↗</a
				>
			{/if}
		</span>
	</div>
	{#if data}
		{#if near.length}
			{@render list(near)}
		{:else}
			<p class="muted small">
				No photos within {away(nearKm)} of {name} in the last {span} days.
			</p>
		{/if}
		{#if zone.length}
			<details class="zone" open={!near.length}>
				<summary>More in {zoneName} <span class="faint small">({zone.length})</span></summary>
				{@render list(zone)}
			</details>
		{/if}
		<p class="faint small note">
			{source}, last {span} days. Public reports aren't checked; what people wrote is on the Backcountry
			tab.
		</p>
	{/if}
	{#if center && !center.shown}
		<p class="faint small note">
			{center.name}'s photos open on its own site; they can't be shown here.
		</p>
	{/if}
</section>

{#if viewer.index !== null && flat.length}
	<PhotoViewer
		photos={flat}
		bind:index={viewer.index}
		grid={gallery}
		{units}
		{tz}
		onclose={viewer.close}
	/>
{/if}

<style>
	.photos {
		margin-top: 16px;
	}
	.top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 6px 12px;
		margin: 0 0 10px;
	}
	h2 {
		margin: 0;
	}
	.links {
		display: flex;
		align-items: center;
		gap: 12px;
		font-size: 0.85rem;
		white-space: nowrap;
	}
	/* The gallery is for wide screens; on a phone a photo is one tap away. */
	.gallery {
		display: none;
	}
	@media (min-width: 720px) {
		.gallery {
			display: inline-flex;
		}
	}
	.report + .report {
		margin-top: 14px;
	}
	.line {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 2px 8px;
		margin: 0 0 6px;
		font-size: 0.9rem;
	}
	.line .faint {
		font-size: 0.8rem;
	}
	.grid {
		display: grid;
		gap: 6px;
		grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
	}
	.grid a {
		display: block;
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
	.zone {
		margin-top: 16px;
		border-top: 1px solid var(--border);
		padding-top: 10px;
	}
	.zone summary {
		cursor: pointer;
		font-weight: 600;
		font-size: 0.9rem;
		margin-bottom: 8px;
	}
	.note {
		margin: 14px 0 0;
	}
	.small {
		font-size: 0.8rem;
	}
</style>
