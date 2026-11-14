<!-- High, medium or low confidence: three bars and the word. No colour scale: this is
     about how sure the forecast is, never about how safe or how good a day is. -->
<script lang="ts">
	import { CONFIDENCE_WORD, type Confidence } from '../confidence';

	let { level, short = false }: { level: Confidence | null; short?: boolean } = $props();
	const n = $derived(level === 'high' ? 3 : level === 'medium' ? 2 : level === 'low' ? 1 : 0);
	const word = $derived(level ? CONFIDENCE_WORD[level] : 'Unknown');
</script>

<span class="meter {level ?? 'none'}" title={short ? `${word} confidence` : undefined}>
	<span class="bars" aria-hidden="true">
		{#each [1, 2, 3] as i (i)}<i class:on={i <= n} style:height="{4 + i * 3}px"></i>{/each}
	</span>
	<span class="word"
		>{word}{#if !short}&nbsp;confidence{:else}<span class="sr-only">&nbsp;confidence</span
			>{/if}</span
	>
</span>

<style>
	.meter {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		padding: 3px 11px 3px 9px;
		border-radius: 999px;
		background: var(--surface-2);
		font-size: 0.8rem;
		font-weight: 600;
		white-space: nowrap;
	}
	.bars {
		display: inline-flex;
		align-items: flex-end;
		gap: 2px;
		height: 13px;
	}
	.bars i {
		width: 4px;
		border-radius: 1.5px;
		background: var(--text-3);
		opacity: 0.3;
	}
	.bars i.on {
		background: var(--text);
		opacity: 1;
	}
	.none .word {
		color: var(--text-2);
		font-weight: 500;
	}
</style>
