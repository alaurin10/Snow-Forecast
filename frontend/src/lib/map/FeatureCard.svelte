<!--
  A map feature tapped on the map (the map panel's content; its name is the panel's
  title): a hut, trailhead or pass with its mapped elevation; a run or route with its
  difficulty and a Profile button; a glacier with its whole area and the elevation where
  it was tapped; an ATES rating with the file it came from. Links to OpenStreetMap when
  the feature's id is known.
-->
<script lang="ts">
	import type { UnitSystem } from '../units';
	import { elevation as fmtElevation } from '../units';
	import { areaText, type HereItem } from './here';
	import { safeHref } from '../links';

	interface Props {
		item: HereItem;
		units: UnitSystem;
		/** A glacier's whole area in m²: undefined while it's worked out, null if unknown. */
		area?: number | null;
		/** The ground's elevation where the map was tapped (glaciers), when known. */
		elevHere?: number | null;
		onprofile?: () => void;
	}

	let { item, units, area, elevHere = null, onprofile }: Props = $props();
	const ateNote =
		"From files this site's owner downloaded from Avalanche Canada's trip planner, as published there.";
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
			{:else if item.type === 'glacier'}
				<div>
					<dt>Elevation here</dt>
					<dd class="num">
						{#if elevHere != null}{fmtElevation(elevHere, units)}{:else}<span class="skel"
							></span>{/if}
					</dd>
				</div>
			{/if}
			{#if item.type === 'glacier'}
				<div>
					<dt>Area</dt>
					<dd class="num">
						{#if area === undefined}<span class="skel"></span>{:else if area}{areaText(
								area,
								units
							)}{:else}<span class="faint">–</span>{/if}
					</dd>
				</div>
			{/if}
		{/if}
	</dl>
	{#if item.line && onprofile}
		<button class="act" onclick={onprofile}>Profile: distance, climb, steepness ›</button>
	{/if}
	<p class="faint small">
		{#if item.type === 'ates'}
			{ateNote}
		{:else}
			From OpenStreetMap, as mapped by volunteers.
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
		gap: 10px;
	}
	.rows {
		margin: 0;
		display: grid;
		gap: 4px;
	}
	.rows div {
		display: grid;
		grid-template-columns: 7.5rem minmax(0, 1fr);
		align-items: baseline;
		gap: 8px;
		min-height: 1.4rem;
	}
	dt {
		font-size: 0.75rem;
		color: var(--text-2);
	}
	dd {
		margin: 0;
		font-weight: 600;
		text-align: right;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
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
	.skel {
		display: inline-block;
		width: 4.5rem;
		height: 0.8rem;
		border-radius: 4px;
		background: var(--grid);
		vertical-align: middle;
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
	}
</style>
