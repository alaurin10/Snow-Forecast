<!--
  What an observer wrote with a field report (NWAC's observations): the signs of
  instability they ticked, as chips, then their summary in paragraphs and their notes on
  instability and avalanches. `clamp` shows the first lines of the summary with "More" to
  read the rest. Nothing for a report without words. (The Backcountry tab; the photo
  viewer keeps to the photos.)
-->
<script lang="ts">
	import type { ObsProps } from '../types.gen';
	import { signLabel } from '../webcams';

	interface Props {
		report: ObsProps;
		/** Show only the first lines of the summary until "More". */
		clamp?: boolean;
	}

	let { report, clamp = false }: Props = $props();
	let open = $state(false);
	const paras = $derived((report.summary ?? '').split('\n\n').filter(Boolean));
	const long = $derived((report.summary ?? '').length > 260 || paras.length > 2);
	const signs = $derived(report.signs ?? []);
	const notes = $derived(
		[
			report.instability_note ? { label: 'Instability', text: report.instability_note } : null,
			report.avalanche_note ? { label: 'Avalanches', text: report.avalanche_note } : null
		].filter((n) => n !== null)
	);
	const shut = $derived(clamp && long && !open);
</script>

{#if signs.length || paras.length || notes.length}
	<div class="words">
		{#if signs.length}
			<ul class="signs" aria-label="Signs of instability reported">
				{#each signs as s (s.kind)}
					<li class:grave={s.kind.startsWith('avalanches')}>{signLabel(s)}</li>
				{/each}
			</ul>
		{/if}
		{#if paras.length || notes.length}
			<div class="text" class:shut>
				{#each paras as p, i (i)}<p>{p}</p>{/each}
				{#each notes as n (n.label)}<p><strong>{n.label}:</strong> {n.text}</p>{/each}
			</div>
			{#if clamp && long}
				<button type="button" class="more" aria-expanded={open} onclick={() => (open = !open)}
					>{open ? 'Less' : 'More'}</button
				>
			{/if}
		{/if}
	</div>
{/if}

<style>
	.words {
		display: grid;
		gap: 6px;
		--chip: var(--surface-2);
		--chip-text: var(--text);
		--grave: var(--warn-ink);
		--grave-bg: var(--warn-bg);
	}
	.signs {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 4px 6px;
	}
	.signs li {
		font-size: 0.78rem;
		padding: 2px 8px;
		border-radius: 999px;
		background: var(--chip);
		color: var(--chip-text);
	}
	.signs li.grave {
		background: var(--grave-bg);
		color: var(--grave);
		font-weight: 600;
	}
	.text {
		display: grid;
		gap: 6px;
		font-size: 0.9rem;
		line-height: 1.45;
	}
	.text p {
		margin: 0;
	}
	.text.shut {
		display: -webkit-box;
		-webkit-line-clamp: 4;
		line-clamp: 4;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.text.shut p + p {
		margin-top: 6px;
	}
	.more {
		justify-self: start;
		padding: 0;
		border: 0;
		background: none;
		color: var(--accent);
		font: inherit;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
	}
</style>
