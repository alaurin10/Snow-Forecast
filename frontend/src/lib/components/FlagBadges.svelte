<!-- Up to a few flags as small badges, most important first. "New" marks one raised this run. -->
<script lang="ts">
	import type { Flag } from '../types.gen';
	import { flagText, flagTitle, isNew } from '../flags';
	import type { UnitSystem } from '../units';

	interface Props {
		flags: Flag[];
		runId?: number | null;
		units: UnitSystem;
		max?: number;
		/** Types shown elsewhere on the page (e.g. alerts and danger chips). */
		exclude?: string[];
	}

	let { flags, runId = null, units, max = 3, exclude = [] }: Props = $props();
	const shown = $derived(flags.filter((f) => !exclude.includes(f.type)).slice(0, max));
</script>

{#if shown.length}
	<span class="badges">
		{#each shown as f, i (i)}
			<span class="badge {f.severity}" title={flagText(f, units)}
				>{flagTitle(f)}{#if isNew(f, runId)}<span class="new">New</span>{/if}</span
			>
		{/each}
	</span>
{/if}

<style>
	.badges {
		display: inline-flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		border-radius: 999px;
		padding: 1px 8px;
		font-size: 0.75rem;
		border: 1px solid var(--border);
		background: var(--surface-2);
		color: var(--text-2);
		white-space: nowrap;
	}
	.badge.notice {
		border-color: var(--snow);
		color: var(--text);
	}
	.badge.warning {
		border-color: var(--temp);
		color: var(--text);
		font-weight: 600;
	}
	.new {
		font-size: 0.65rem;
		font-weight: 700;
		text-transform: uppercase;
		color: var(--snow);
	}
</style>
