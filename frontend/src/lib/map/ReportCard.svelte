<!--
  One field report from Avalanche Canada's Mountain Information Network, tapped on the
  map (the map panel's content; its title is the panel's): when, where, what kinds of
  observation it has, and a link to read it in full on avalanche.ca. What someone saw,
  not checked by anyone.
-->
<script lang="ts">
	import type { ObsProps } from '../types.gen';
	import { ago, REPORT_KINDS } from './features';
	import { safeHref } from '../links';

	interface Props {
		report: ObsProps;
	}

	let { report }: Props = $props();
	const when = $derived(
		new Date(report.time).toLocaleString('en-US', {
			weekday: 'short',
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		})
	);
</script>

<div class="content">
	<span class="faint where"
		>{when} · {ago(report.time)}{report.region ? ` · ${report.region}` : ''}</span
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
		From Avalanche Canada’s Mountain Information Network: what someone in the mountains saw and
		chose to share, not checked.{report.images
			? ` ${report.images} photo${report.images > 1 ? 's' : ''}.`
			: ''}
	</p>
	{#if safeHref(report.url)}
		<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
		<a href={safeHref(report.url)} target="_blank" rel="noopener noreferrer"
			>Read it on avalanche.ca →</a
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
