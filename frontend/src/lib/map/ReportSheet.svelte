<!--
  One field report from Avalanche Canada's Mountain Information Network, tapped on the
  map: its title, when, where, what kinds of observation it has, and a link to read it
  in full on avalanche.ca. What someone saw, not checked by anyone.
-->
<script lang="ts">
	import type { ObsProps } from '../types.gen';
	import { ago, REPORT_KINDS } from './features';
	import { safeHref } from '../links';

	interface Props {
		report: ObsProps;
		onclose: () => void;
	}

	let { report, onclose }: Props = $props();
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

<div class="sheet" role="dialog" aria-label="Field report">
	<div class="head">
		<strong>{report.title || 'Field report'}</strong>
		<span class="faint"
			>{when} · {ago(report.time)}{report.region ? ` · ${report.region}` : ''}</span
		>
	</div>
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
	<button class="close" onclick={onclose}>Close</button>
</div>

<style>
	.sheet {
		position: absolute;
		top: 56px;
		left: calc(var(--map-inset, 0px) + 60px);
		right: 10px;
		max-width: 340px;
		z-index: 1003;
		padding: 12px 14px;
		border-radius: 14px;
		background: var(--surface);
		border: 1px solid var(--border);
		box-shadow: var(--glass-shadow);
		font-size: 0.85rem;
		color: var(--text);
		display: grid;
		gap: 8px;
	}
	.head {
		display: grid;
		gap: 2px;
	}
	.head .faint {
		font-size: 0.75rem;
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
	.close {
		justify-self: end;
		border: 0;
		background: transparent;
		color: var(--accent);
		font-weight: 600;
		cursor: pointer;
		padding: 4px 6px;
	}
</style>
