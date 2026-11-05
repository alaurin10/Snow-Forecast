<!-- A ski-day rating: Powder, Great, Good, Fair or Poor. -->
<script lang="ts">
	interface Props {
		rating: string | null | undefined;
		score: number | null | undefined;
	}

	let { rating, score }: Props = $props();
</script>

{#if rating && score}
	<span class="rating r{score}">{score === 5 ? '★ ' : ''}{rating}</span>
{/if}
