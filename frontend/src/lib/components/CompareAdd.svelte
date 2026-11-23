<!-- Compare: every location, to tick the ones to compare. Nothing is ticked for you. Each
     shows its region and its 5-day snow at mid; a search box appears once there are more
     than eight. Locations without a forecast are listed but can't be ticked. -->
<script module lang="ts">
	export interface AddItem {
		id: string;
		name: string;
		region: string;
		kind: string;
		/** "4.2 in", the next 5 days at mid. */
		next5: string;
		ready: boolean;
	}
</script>

<script lang="ts">
	import { MAX_LOCS } from '../compare';

	interface Props {
		items: AddItem[];
		picked: string[];
		ontoggle: (id: string) => void;
	}

	let { items, picked, ontoggle }: Props = $props();
	let query = $state('');

	const full = $derived(picked.length >= MAX_LOCS);
	const shown = $derived.by(() => {
		const q = query.trim().toLocaleLowerCase();
		return q ? items.filter((i) => `${i.name} ${i.region}`.toLocaleLowerCase().includes(q)) : items;
	});
</script>

<div class="add">
	{#if items.length > 8}
		<input
			class="search"
			type="search"
			placeholder="Search locations"
			aria-label="Search locations"
			bind:value={query}
		/>
	{/if}
	<p class="count" aria-live="polite">
		{picked.length} of {MAX_LOCS} picked{#if full}<span class="faint">
				· that’s the most in one comparison</span
			>{/if}
	</p>
	<ul>
		{#each shown as it (it.id)}
			{@const on = picked.includes(it.id)}
			<li>
				<button
					class="item"
					aria-pressed={on}
					disabled={!it.ready || (full && !on)}
					onclick={() => ontoggle(it.id)}
				>
					<span class="box" class:on aria-hidden="true">
						{#if on}<svg viewBox="0 0 24 24" width="14" height="14"><path d="M5 12l5 5 9-10" /></svg
							>{/if}
					</span>
					<span class="text">
						<strong>{it.name}</strong>
						<small
							>{it.region}{it.kind === 'backcountry' ? ' · Backcountry' : ''}{#if !it.ready}
								· No forecast yet{/if}</small
						>
					</span>
					{#if it.ready}<span class="amt num" title="Next 5 days at mid">{it.next5}</span>{/if}
				</button>
			</li>
		{:else}
			<li class="faint none">No location matches “{query}”.</li>
		{/each}
	</ul>
</div>

<style>
	.add {
		display: grid;
		gap: 8px;
		min-width: 0;
	}
	.search {
		width: 100%;
		box-sizing: border-box;
		min-height: 40px;
		padding: 0 14px;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
		color: var(--text);
		font: inherit;
	}
	.count {
		margin: 0;
		font-size: 0.8rem;
		color: var(--text-2);
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 2px;
	}
	.item {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 12px;
		min-height: 48px;
		padding: 6px 10px;
		border: 0;
		border-radius: 14px;
		background: transparent;
		text-align: left;
		cursor: pointer;
	}
	.item:hover:not(:disabled) {
		background: var(--hover);
	}
	.item:disabled {
		cursor: default;
		opacity: 0.5;
	}
	.box {
		flex: 0 0 22px;
		height: 22px;
		display: grid;
		place-items: center;
		box-sizing: border-box;
		border: 2px solid var(--text-3);
		border-radius: 7px;
	}
	.box.on {
		border-color: var(--accent);
		background: var(--accent);
		color: var(--on-accent);
	}
	.box svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 3;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.text {
		flex: 1;
		min-width: 0;
		display: grid;
	}
	.text strong {
		font-size: 0.92rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.text small {
		font-size: 0.76rem;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.amt {
		flex: 0 0 auto;
		font-size: 0.84rem;
		font-weight: 600;
		color: var(--text-2);
	}
	.none {
		padding: 10px;
		font-size: 0.86rem;
	}
</style>
