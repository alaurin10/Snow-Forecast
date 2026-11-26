<!--
  The Backcountry tab's recent observations: what forecasters and people in the mountains
  reported around the location over the last two weeks (NWAC's observations, and
  Avalanche Canada's field reports), newest first. Those near the location (within 20 km
  and closer to it than to any other location) first, then, folded, the rest of its
  avalanche zone. Each with who sent it, the day, the place and how far away, the signs of
  instability they reported, their summary (first lines, then More), small photos that
  open the full-screen viewer, and a link to the full report. Past conditions, not a
  forecast; public reports aren't checked by anyone.
-->
<script lang="ts">
	import { safeHref, safeImage } from '../links';
	import type { LoadState } from '../load';
	import type { NearbyOut, NearbyReport } from '../types.gen';
	import type { UnitSystem } from '../units';
	import { reportFrom, reportWhen, type CenterObservations, type ViewerPhoto } from '../webcams';
	import ObsWords from '../webcams/ObsWords.svelte';
	import PhotoViewer from '../webcams/PhotoViewer.svelte';
	import { photoViewer } from '../webcams/viewer.svelte';

	interface Props {
		data: NearbyOut | null;
		load?: LoadState;
		units: UnitSystem;
		tz?: string | null;
		name?: string;
		/** The location's avalanche center's observations page. */
		center?: CenterObservations | null;
	}

	let {
		data,
		load = 'ready',
		units,
		tz = null,
		name = 'this location',
		center = null
	}: Props = $props();

	const THUMBS = 4;
	const reports = $derived(data?.area_reports ?? []);
	const near = $derived(reports.filter((r) => r.group !== 'zone'));
	const zone = $derived(reports.filter((r) => r.group === 'zone'));
	const zoneName = $derived(data?.zone_name || 'the avalanche zone');
	const span = $derived(data?.reports_days ?? 14);
	const nearKm = $derived(data?.near_km ?? 20);
	const away = (km: number) =>
		units === 'imperial' ? `${(km * 0.621371).toFixed(0)} mi` : `${km.toFixed(0)} km`;

	// Every photo in the list, near first, for the viewer to flip through.
	const flat = $derived(
		[...near, ...zone].flatMap((r) =>
			(r.report.photos ?? [])
				.filter((ph) => safeImage(ph.thumb) && safeImage(ph.url))
				.map((photo): ViewerPhoto => ({ photo, report: r.report, distance_km: r.distance_km }))
		)
	);
	const first = $derived(new Map(flat.map((p, i) => [p.photo.url + '\n' + p.report.id, i])));
	const viewer = photoViewer();
</script>

{#snippet item(r: NearbyReport)}
	{@const pics = (r.report.photos ?? []).filter((ph) => safeImage(ph.thumb) && safeImage(ph.url))}
	<li class="obs">
		<p class="title">
			{#if safeHref(r.report.url)}
				<!-- External site: resolve() is only for routes in this app. -->
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<a href={safeHref(r.report.url)} target="_blank" rel="noopener noreferrer"
					>{r.report.title || 'Field report'}</a
				>
			{:else}
				<strong>{r.report.title || 'Field report'}</strong>
			{/if}
		</p>
		<p class="meta faint">
			{reportWhen(r.report, tz)} · {reportFrom(r.report)} · {away(r.distance_km)} away{r.report
				.region
				? ` · ${r.report.region}`
				: ''}
		</p>
		<ObsWords report={r.report} clamp />
		{#if pics.length}
			<div class="thumbs">
				{#each pics.slice(0, THUMBS) as ph, i (i)}
					{@const at = first.get(ph.url + '\n' + r.report.id)}
					{#if at !== undefined}
						<!-- eslint-disable svelte/no-navigation-without-resolve -->
						<a
							href={safeHref(ph.url)}
							target="_blank"
							rel="noopener noreferrer"
							aria-haspopup="dialog"
							aria-label={i === THUMBS - 1 && pics.length > THUMBS
								? `${pics.length} photos from “${r.report.title || 'this report'}”, full screen`
								: `Photo ${i + 1} from “${r.report.title || 'this report'}”, full screen`}
							onclick={(e) => viewer.open(at, e)}
						>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
							<img src={safeImage(ph.thumb)} alt="" loading="lazy" referrerpolicy="no-referrer" />
							{#if i === THUMBS - 1 && pics.length > THUMBS}
								<span class="more-pics">+{pics.length - THUMBS + 1}</span>
							{/if}
						</a>
					{/if}
				{/each}
			</div>
		{/if}
	</li>
{/snippet}

{#if data && (reports.length || center?.shown)}
	<section class="card recent">
		<h2>Recent observations</h2>
		<p class="faint small">
			What forecasters and people in the mountains reported in the last {span} days. Past conditions,
			not a forecast; public reports aren't checked by anyone.
		</p>
		<h3>Near {name}</h3>
		{#if near.length}
			<ul class="list">
				{#each near as r (r.report.id)}{@render item(r)}{/each}
			</ul>
		{:else}
			<p class="muted small">
				No observations within {away(nearKm)} of {name} in the last {span} days.
			</p>
		{/if}
		{#if zone.length}
			<details class="zone" open={!near.length}>
				<summary
					>More in {zoneName}
					<span class="faint small"
						>({zone.length} observation{zone.length > 1 ? 's' : ''}, closer to other places)</span
					></summary
				>
				<ul class="list">
					{#each zone as r (r.report.id)}{@render item(r)}{/each}
				</ul>
			</details>
		{/if}
		{#if center?.shown && safeHref(center.url)}
			<p class="center">
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<a href={safeHref(center.url)} target="_blank" rel="noopener noreferrer"
					>All {center.name} observations ↗</a
				>
			</p>
		{/if}
	</section>
{:else if load === 'loading' && center?.shown}
	<section class="card recent">
		<h2>Recent observations</h2>
		<p class="muted small">Loading…</p>
	</section>
{/if}

{#if viewer.index !== null && flat.length}
	<PhotoViewer photos={flat} bind:index={viewer.index} {units} {tz} onclose={viewer.close} />
{/if}

<style>
	h2 {
		margin: 0 0 4px;
	}
	h3 {
		margin: 16px 0 6px;
		font-size: 0.95rem;
	}
	.small {
		font-size: 0.82rem;
	}
	.recent > p {
		margin: 0;
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
	}
	.obs {
		display: grid;
		gap: 6px;
		padding: 12px 0;
		border-top: 1px solid var(--border);
	}
	.obs:first-child {
		border-top: 0;
		padding-top: 4px;
	}
	.obs p {
		margin: 0;
	}
	.title {
		font-weight: 600;
	}
	.meta {
		font-size: 0.8rem;
	}
	.thumbs {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 96px));
		gap: 6px;
	}
	.thumbs a {
		position: relative;
		display: block;
		cursor: zoom-in;
	}
	.thumbs img {
		display: block;
		width: 100%;
		aspect-ratio: 1;
		object-fit: cover;
		border-radius: 6px;
		background: var(--surface-2);
	}
	.more-pics {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		border-radius: 6px;
		background: rgb(8 14 28 / 0.55);
		color: #fff;
		font-weight: 700;
	}
	.zone {
		margin-top: 10px;
		border-top: 1px solid var(--border);
		padding-top: 10px;
	}
	.zone summary {
		cursor: pointer;
		font-weight: 600;
	}
	.center {
		margin-top: 12px !important;
		font-size: 0.88rem;
	}
</style>
