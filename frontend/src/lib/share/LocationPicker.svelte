<!-- Which locations go in a share image: a "Locations 8 of 13" button that opens a set of
     toggle chips, each with its total, up to `max` picked. -->
<script lang="ts">
	interface Item {
		id: string;
		name: string;
		/** Shown after the name, e.g. "12.4 in". */
		total: string;
	}

	interface Props {
		items: Item[];
		/** Picked ids. */
		picked: string[];
		max: number;
		onchange: (ids: string[]) => void;
		/** The ids a reset goes back to, e.g. the snowiest. */
		defaults: string[];
		defaultsLabel: string;
	}

	let { items, picked, max, onchange, defaults, defaultsLabel }: Props = $props();
	let open = $state(false);

	const set = $derived(new Set(picked));
	const full = $derived(picked.length >= max);
	const isDefault = $derived(
		defaults.length === picked.length && defaults.every((id) => set.has(id))
	);

	function toggle(id: string) {
		if (set.has(id)) onchange(picked.filter((x) => x !== id));
		else if (!full) onchange([...picked, id]);
	}
</script>

<button
	class="pick"
	aria-expanded={open}
	aria-controls="share-locations"
	onclick={() => (open = !open)}
>
	Locations <span class="count">{picked.length} of {items.length}</span>
	<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" class:up={open}
		><path d="M6 9l6 6 6-6" /></svg
	>
</button>

{#if open}
	<div class="panel" id="share-locations">
		<div class="bar">
			<span class="muted">
				{#if full}Up to {max} fit in one image.{:else}Pick up to {max}.{/if}
			</span>
			<span class="acts">
				<button class="link" disabled={isDefault} onclick={() => onchange([...defaults])}
					>{defaultsLabel}</button
				>
				<button class="link" disabled={!picked.length} onclick={() => onchange([])}>Clear</button>
			</span>
		</div>
		<div class="chips" role="group" aria-label="Locations in the image">
			{#each items as it (it.id)}
				<button
					class="chip"
					aria-pressed={set.has(it.id)}
					disabled={!set.has(it.id) && full}
					onclick={() => toggle(it.id)}
				>
					{#if set.has(it.id)}<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"
							><path d="M5 12.5l4.5 4.5L19 7.5" /></svg
						>{/if}
					<span class="name">{it.name}</span>
					<span class="num tot">{it.total}</span>
				</button>
			{/each}
		</div>
	</div>
{/if}

<style>
	.pick {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		height: 34px;
		padding: 0 12px;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: var(--surface-2);
		color: var(--text);
		font-size: 0.86rem;
		font-weight: 500;
		cursor: pointer;
	}
	.count {
		color: var(--text-2);
	}
	.pick svg,
	.chip svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2.2;
		stroke-linecap: round;
		stroke-linejoin: round;
		transition: transform var(--ease);
	}
	.pick svg.up {
		transform: rotate(180deg);
	}
	/* The chips take their own line under the shape and Locations buttons. */
	.panel {
		flex: 1 0 100%;
		display: grid;
		gap: 8px;
	}
	.bar {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
		font-size: 0.8rem;
	}
	.acts {
		display: flex;
		gap: 4px;
		flex-shrink: 0;
	}
	.link {
		border: 0;
		background: none;
		padding: 4px 6px;
		color: var(--accent-ink, var(--accent));
		font-size: 0.8rem;
		font-weight: 600;
		cursor: pointer;
	}
	.link:disabled {
		color: var(--text-3);
		cursor: default;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		max-height: 30dvh;
		overflow-y: auto;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		max-width: 100%;
		padding: 6px 11px;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: transparent;
		color: var(--text-2);
		font-size: 0.82rem;
		cursor: pointer;
		transition:
			background-color var(--ease),
			color var(--ease),
			border-color var(--ease);
	}
	.chip .name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.chip .tot {
		color: var(--text-3);
		font-size: 0.76rem;
		flex-shrink: 0;
	}
	.chip[aria-pressed='true'] {
		background: var(--accent-soft);
		border-color: var(--accent);
		color: var(--text);
		padding-left: 8px;
	}
	.chip svg {
		flex-shrink: 0;
		stroke: var(--accent);
		stroke-width: 3;
	}
	.chip[aria-pressed='true'] .tot {
		color: var(--text-2);
	}
	.chip:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
</style>
