<!--
  One field report tapped on the map (the map panel's content; its title is the panel's),
  from Avalanche Canada's Mountain Information Network or NWAC's observations: when,
  where, who sent it, what kinds of observation it has, and a link to read it in full on
  avalanche.ca or nwac.us. Public reports are what someone saw, not checked by anyone.
-->
<script lang="ts">
	import type { ObsProps } from '../types.gen';
	import { ago, REPORT_KINDS } from './features';
	import { safeHref } from '../links';
	import { reportFrom, reportWhen } from '../webcams';

	interface Props {
		report: ObsProps;
	}

	let { report }: Props = $props();
	const nwac = $derived(report.source === 'nwac');
	// NWAC's observations give the day, not the time: no "hours ago" for them.
	const when = $derived(reportWhen(report) + (report.day ? '' : ` · ${ago(report.time)}`));
	const photos = $derived(
		report.images ? ` ${report.images} photo${report.images > 1 ? 's' : ''}.` : ''
	);
</script>

<div class="content">
	<span class="faint where"
		>{when} · {reportFrom(report)}{report.region ? ` · ${report.region}` : ''}</span
	>
	{#if report.kinds.length}
		<ul class="kinds" aria-label="What it reports">
			{#each report.kinds as k (k)}
				<li>
					<span class="dot" style:background={REPORT_KINDS[k]?.color}></span>
					{REPORT_KINDS[k]?.label ?? k}
				</li>
			{/each}
		</ul>
	{/if}
	<p class="faint small">
		{#if nwac}
			From NWAC’s observations page: what {report.observer === 'forecaster'
				? 'a forecaster'
				: 'someone in the mountains'} saw and shared{report.observer === 'forecaster'
				? ''
				: ', not checked'}.{photos}
		{:else}
			From Avalanche Canada’s Mountain Information Network: what someone in the mountains saw and
			chose to share, not checked.{photos}
		{/if}
	</p>
	{#if safeHref(report.url)}
		<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
		<a href={safeHref(report.url)} target="_blank" rel="noopener noreferrer"
			>Read it on {nwac ? 'nwac.us' : 'avalanche.ca'} →</a
		>
	{/if}
</div>

<style>
	.content {
		display: grid;
		gap: 10px;
	}
	.where {
		font-size: 0.78rem;
	}
	.kinds {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		font-size: 0.8rem;
	}
	.kinds li {
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}
	.dot {
		width: 9px;
		height: 9px;
		border-radius: 50%;
	}
	.small {
		margin: 0;
		font-size: 0.72rem;
	}
	a {
		font-weight: 600;
	}
</style>
