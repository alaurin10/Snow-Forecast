<!-- Avalanche danger as a chip: the colour, the number and the word, or why there is none. -->
<script lang="ts">
	import { dangerStatusText, dangerWord } from '../conditions';

	interface Props {
		level: number | null | undefined;
		status: string;
		/** Prefix, e.g. "Avalanche". */
		label?: string;
	}

	let { level, status, label = '' }: Props = $props();
	const rated = $derived(status === 'current' && !!level);
</script>

{#if rated}
	<span class="danger d{level}" title={`Avalanche danger ${level} – ${dangerWord(level)}`}
		>{label ? `${label} ` : ''}{level} · {dangerWord(level)}</span
	>
{:else}
	<span class="danger d0">{label ? `${label}: ` : ''}{dangerStatusText(status)}</span>
{/if}
