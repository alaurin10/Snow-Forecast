<!--
  A map feature tapped on the map (the map panel's content; its name is the panel's
  title): a hut, trailhead or pass with its mapped elevation; a run or route with its
  difficulty and a Profile button; an ATES rating with the file it came from; a glacier
  with what the terrain says of it (its top and toe, the way it flows, how steep, how
  long, its whole area) and the forecast snow at its top and its toe. Links to
  OpenStreetMap, and a glacier's Wikipedia article, when they're known.
-->
<script lang="ts">
	import type { UnitSystem } from '../units';
	import { elevation as fmtElevation, snow as fmtSnow } from '../units';
	import { areaText, type HereItem } from './here';
	import { STEEP_DEG, type GlacierInfo } from './glacier';
	import { distanceText, heightText } from './measure';
	import { sectorOf } from './terrain/analysis';
	import { snowAtElevation } from './layers/snowtiles';
	import { safeHref } from '../links';

	interface Props {
		item: HereItem;
		units: UnitSystem;
		/** A glacier's numbers, as they come in. */
		glacier?: GlacierInfo | null;
		onprofile?: () => void;
	}

	let { item, units, glacier = null, onprofile }: Props = $props();
	const ateNote =
		"From files this site's owner downloaded from Avalanche Canada's trip planner, as published there.";
	const FLOWS: Record<string, string> = {
		N: 'north',
		NE: 'northeast',
		E: 'east',
		SE: 'southeast',
		S: 'south',
		SW: 'southwest',
		W: 'west',
		NW: 'northwest'
	};
	const typeWord = $derived(
		item.glacierType
			? `${item.glacierType[0].toUpperCase()}${item.glacierType.slice(1).replace(/_/g, ' ')} glacier`
			: 'Glacier'
	);
	const stats = $derived(glacier?.stats);
	/** Forecast snow at the glacier's top and toe (or for the area, if that's all there is). */
	const snow = $derived.by(() => {
		const p = glacier?.point;
		if (!p || !p.inside || !p.totals.length) return null;
		const windows = [24, 72, 168];
		const elevs = p.elevations ?? [];
		const at = (w: number, m: number) =>
			snowAtElevation(p.totals.find((t) => t.window === w)?.by_elevation, elevs, m);
		const rows: { label: string; cm: (number | null)[] }[] = [];
		if (stats) {
			const top = windows.map((w) => at(w, stats.top));
			const toe = windows.map((w) => at(w, stats.toe));
			if (top.some((v) => v != null))
				rows.push({ label: 'Top', cm: top }, { label: 'Toe', cm: toe });
		}
		if (!rows.length)
			rows.push({
				label: 'Area',
				cm: windows.map((w) => p.totals.find((t) => t.window === w)?.cm ?? null)
			});
		const now = Date.now() / 1000;
		const level = p.snow_level.find((x) => x.t >= now - 1800)?.value ?? null;
		return { rows, level };
	});
	const icy = $derived(item.type === 'glacier');
	/** Still waiting for the forecast, or for the heights it's read at. */
	const snowLoading = $derived(
		glacier?.pointState === 'loading' || (glacier?.pointState === 'ready' && stats === undefined)
	);
</script>

<div class="content">
	<dl class="rows">
		{#if item.type === 'ates'}
			<div>
				<dt>Rating</dt>
				<dd>
					{#if item.color}<i style:background={item.color} aria-hidden="true"></i>{/if}{item.name}
				</dd>
			</div>
			{#if item.detail}
				<div>
					<dt>Area</dt>
					<dd title={item.detail}>{item.detail}</dd>
				</div>
			{/if}
			{#if item.file}
				<div>
					<dt>File</dt>
					<dd title={item.file}>{item.file}</dd>
				</div>
			{/if}
		{:else if icy}
			<div>
				<dt>Type</dt>
				<dd>{typeWord}</dd>
			</div>
			<div>
				<dt>Area</dt>
				<dd class="num">
					{#if glacier?.area === undefined}<span class="skel"></span>
					{:else if glacier.area}{areaText(glacier.area, units)}
					{:else}<span class="faint">–</span>{/if}
				</dd>
			</div>
			<div>
				<dt>Elevation</dt>
				<dd class="num">
					{#if stats === undefined}<span class="skel"></span>
					{:else if stats}{fmtElevation(stats.toe, units)} – {fmtElevation(stats.top, units)}
					{:else}<span class="faint">–</span>{/if}
				</dd>
			</div>
			<div>
				<dt>Top to toe</dt>
				<dd class="num">
					{#if stats === undefined}<span class="skel"></span>
					{:else if stats}{distanceText(stats.length, units)}
						<span class="faint">· {heightText(stats.top - stats.toe, units)} drop</span>
					{:else}<span class="faint">–</span>{/if}
				</dd>
			</div>
			<div>
				<dt>Flows</dt>
				<dd>
					{#if stats === undefined}<span class="skel short"></span>
					{:else if stats?.flows != null}
						{FLOWS[sectorOf(stats.flows)]}
					{:else if stats}<span class="faint">every way</span>
					{:else}<span class="faint">–</span>{/if}
				</dd>
			</div>
			<div>
				<dt>Slope</dt>
				<dd class="num">
					{#if stats === undefined}<span class="skel"></span>
					{:else if stats}{Math.round(stats.slope)}° average
						<span class="faint">· {Math.round(stats.steep * 100)}% over {STEEP_DEG}°</span>
					{:else}<span class="faint">–</span>{/if}
				</dd>
			</div>
		{:else}
			<div>
				<dt>Type</dt>
				<dd>{item.kind}</dd>
			</div>
			{#if item.type === 'route' && item.detail}
				<div>
					<dt>Grade</dt>
					<dd title={item.detail}>{item.detail}</dd>
				</div>
			{/if}
			{#if item.ele != null}
				<div>
					<dt>Elevation</dt>
					<dd class="num">{fmtElevation(item.ele, units)}</dd>
				</div>
			{/if}
		{/if}
	</dl>

	{#if icy && glacier}
		<section aria-label="Forecast snow on the glacier">
			<h3>Forecast snow</h3>
			{#if snowLoading}
				<table class="snow" aria-busy="true" aria-label="Loading the forecast here">
					<thead><tr><th></th><th>24 h</th><th>3 days</th><th>7 days</th></tr></thead>
					<tbody>
						{#each ['Top', 'Toe'] as k (k)}
							<tr>
								<th>{k}</th>
								{#each [0, 1, 2] as i (i)}<td><span class="skel tiny"></span></td>{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			{:else if snow}
				<table class="snow" aria-label="Forecast snow">
					<thead><tr><th></th><th>24 h</th><th>3 days</th><th>7 days</th></tr></thead>
					<tbody>
						{#each snow.rows as r (r.label)}
							<tr>
								<th scope="row">{r.label}</th>
								{#each r.cm as v, i (i)}<td>{fmtSnow(v, units)}</td>{/each}
							</tr>
						{/each}
					</tbody>
				</table>
				{#if snow.level != null}
					<dl class="rows">
						<div>
							<dt>Snow level now</dt>
							<dd class="num">
								{fmtElevation(snow.level, units)}
								{#if stats && snow.level > stats.toe}
									<span class="faint">· rain possible low down</span>
								{/if}
							</dd>
						</div>
					</dl>
				{/if}
			{:else}
				<p class="faint small">
					{glacier.pointState === 'failed'
						? "The forecast here couldn't be loaded."
						: "Outside the area the map's weather covers."}
				</p>
			{/if}
		</section>
	{/if}

	{#if item.line && onprofile}
		<button class="act" onclick={onprofile}>Profile: distance, climb, steepness ›</button>
	{/if}
	<p class="faint small">
		{#if item.type === 'ates'}
			{ateNote}
		{:else}
			{#if icy}
				Heights, slope and direction from the terrain model over the outline as mapped; snow from
				the map's weather at the top's and the toe's heights. Crevasses aren't mapped.
			{/if}
			From OpenStreetMap, as mapped by volunteers.
			{#if item.wiki && safeHref(item.wiki)}
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<a href={safeHref(item.wiki)} target="_blank" rel="noopener noreferrer">Wikipedia ↗</a>
			{/if}
			{#if item.link && safeHref(item.link)}
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<a href={safeHref(item.link)} target="_blank" rel="noopener noreferrer"
					>See it on OpenStreetMap ↗</a
				>
			{/if}
		{/if}
	</p>
</div>

<style>
	.content {
		display: grid;
		gap: 12px;
	}
	section {
		display: grid;
		gap: 6px;
	}
	h3 {
		margin: 0;
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-2);
	}
	.rows {
		margin: 0;
		display: grid;
		gap: 2px;
	}
	.rows div {
		display: grid;
		grid-template-columns: 6.5rem minmax(0, 1fr);
		align-items: center;
		gap: 8px;
		min-height: 1.45rem;
	}
	dt {
		font-size: 0.75rem;
		color: var(--text-2);
		white-space: nowrap;
	}
	dd {
		margin: 0;
		font-weight: 600;
		font-size: 0.82rem;
		text-align: right;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	dd .faint {
		font-weight: 500;
		font-size: 0.76rem;
	}
	.num {
		font-variant-numeric: tabular-nums;
	}
	i {
		display: inline-block;
		width: 10px;
		height: 10px;
		margin-right: 6px;
		border-radius: 3px;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.15);
	}
	.snow {
		width: 100%;
		border-collapse: collapse;
		table-layout: fixed;
		font-size: 0.82rem;
		font-variant-numeric: tabular-nums;
	}
	.snow th,
	.snow td {
		height: 1.45rem;
		padding: 0 0 0 8px;
		text-align: right;
		white-space: nowrap;
	}
	.snow th:first-child {
		width: 6.5rem;
		padding-left: 0;
		text-align: left;
	}
	.snow thead th {
		height: 1.1rem;
		font-size: 0.7rem;
		font-weight: 500;
		color: var(--text-2);
	}
	.snow tbody th {
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--text-2);
	}
	.snow td {
		font-weight: 600;
	}
	.skel {
		display: inline-block;
		width: 4.5rem;
		height: 0.8rem;
		border-radius: 4px;
		background: var(--grid);
		vertical-align: middle;
	}
	.skel.short {
		width: 2.5rem;
	}
	.skel.tiny {
		width: 2.6rem;
	}
	@media (prefers-reduced-motion: no-preference) {
		.skel {
			animation: pulse 1.4s ease-in-out infinite;
		}
	}
	@keyframes pulse {
		50% {
			opacity: 0.45;
		}
	}
	.act {
		justify-self: start;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: transparent;
		color: var(--accent-ink, var(--accent));
		font: inherit;
		font-size: 0.8rem;
		font-weight: 600;
		padding: 6px 12px;
		cursor: pointer;
	}
	.act:hover {
		background: var(--hover);
	}
	.small {
		margin: 0;
		font-size: 0.72rem;
	}
	a {
		font-weight: 600;
		margin-right: 6px;
	}
</style>
