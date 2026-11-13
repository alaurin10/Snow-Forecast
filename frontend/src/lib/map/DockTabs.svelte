<!--
  Phones and tablets: one row naming the controls at the foot of the map (Weather,
  Terrain, Satellite…). A tap opens that control above the row (and folds the one that
  was open); a tap on the open one folds it, leaving just this row over the map.
-->
<script lang="ts">
	interface Tab {
		id: string;
		title: string;
		/** What it shows now, in a few words (said to screen readers, and on hover). */
		status: string;
	}

	interface Props {
		tabs: Tab[];
		open: string | null;
		onpick: (id: string | null) => void;
	}

	let { tabs, open, onpick }: Props = $props();
</script>

<div class="docktabs glass" role="group" aria-label="Map controls">
	{#each tabs as t (t.id)}
		<button
			aria-pressed={open === t.id}
			aria-label="{t.title}: {t.status}"
			title="{t.title}: {t.status}"
			onclick={() => onpick(open === t.id ? null : t.id)}
		>
			<span>{t.title}</span>
			<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"
				><path d={open === t.id ? 'M6 9l6 6 6-6' : 'M6 15l6-6 6 6'} /></svg
			>
		</button>
	{/each}
</div>

<style>
	.docktabs {
		justify-self: center;
		width: auto !important;
		max-width: 100%;
		display: flex;
		gap: 2px;
		padding: 3px;
		border-radius: 999px;
		background: color-mix(in srgb, var(--surface) 88%, transparent);
		overflow-x: auto;
		scrollbar-width: none;
	}
	.docktabs::-webkit-scrollbar {
		display: none;
	}
	button {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		height: 32px;
		padding: 0 12px;
		border: 0;
		border-radius: 999px;
		background: transparent;
		color: var(--text-2);
		font: inherit;
		font-size: 0.8rem;
		font-weight: 500;
		white-space: nowrap;
		cursor: pointer;
		transition:
			background-color var(--ease),
			box-shadow var(--ease),
			color var(--ease);
	}
	button[aria-pressed='true'] {
		background: var(--sel);
		color: var(--text);
		box-shadow: var(--sel-shadow);
	}
	svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2.2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
</style>
