<!--
  What an observer wrote with a field report (NWAC's observations): the signs of
  instability they ticked, as chips coloured the way NWAC's site colours them (red for
  avalanches, orange for collapsing and cracking), then their summary in paragraphs and their notes on
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
					<li class={s.kind.startsWith('avalanches') ? 'avy' : 'crack'}>{signLabel(s)}</li>
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
		font-weight: 600;
		padding: 2px 9px;
		border-radius: 999px;
	}
	/* As on NWAC's observations: red for avalanches, orange for collapsing and cracking. */
	.signs li.avy {
		background: light-dark(#fde8e8, rgb(239 68 68 / 0.2));
		color: light-dark(#c81e1e, #fca5a5);
	}
	.signs li.crack {
		background: light-dark(#fff1e0, rgb(249 115 22 / 0.2));
		color: light-dark(#b8480b, #fdba74);
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
