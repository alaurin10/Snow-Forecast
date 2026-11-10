<!-- Jump to a location: Ctrl/⌘ K anywhere. Type to filter, arrows to move, Enter to
     open, Escape to close. -->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { modal } from '../modal';

	interface Props {
		locations: { id: string; name: string; region: string }[];
		onclose: () => void;
	}
	let { locations, onclose }: Props = $props();

	let q = $state('');
	let at = $state(0);
	const shown = $derived(
		locations.filter((l) => `${l.name} ${l.region}`.toLowerCase().includes(q.trim().toLowerCase()))
	);
	const open = (id: string) => {
		onclose();
		void goto(resolve('/location/[id]', { id }));
	};
	function onkey(e: KeyboardEvent) {
		if (e.key === 'ArrowDown') at = Math.min(shown.length - 1, at + 1);
		else if (e.key === 'ArrowUp') at = Math.max(0, at - 1);
		else if (e.key === 'Enter' && shown[at]) open(shown[at].id);
		else return;
		e.preventDefault();
	}
</script>

<div class="wrap" use:modal={{ onclose }}>
	<button class="scrim" aria-label="Close" tabindex="-1" onclick={onclose}></button>
	<div class="sheet glass" role="dialog" aria-modal="true" aria-label="Jump to a location">
		<label class="field">
			<span class="sr-only">Jump to a location</span>
			<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"
				><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg
			>
			<input
				type="search"
				placeholder="Jump to a location"
				bind:value={q}
				oninput={() => (at = 0)}
				onkeydown={onkey}
				autocomplete="off"
			/>
		</label>
		<ul role="listbox" aria-label="Locations">
			{#each shown as l, i (l.id)}
				<li role="option" aria-selected={i === at}>
					<a
						href={resolve('/location/[id]', { id: l.id })}
						class:on={i === at}
						onclick={onclose}
						onmouseenter={() => (at = i)}
					>
						<strong>{l.name}</strong><span class="faint">{l.region}</span>
					</a>
				</li>
			{:else}
				<li class="none muted">No location matches “{q}”.</li>
			{/each}
		</ul>
		<p class="hint faint">↑ ↓ to move · Enter to open · Esc to close</p>
	</div>
</div>

<style>
	.wrap {
		position: fixed;
		inset: 0;
		z-index: 60;
		display: grid;
		justify-items: center;
		align-items: start;
		padding: 12vh 16px 16px;
	}
	.scrim {
		position: fixed;
		inset: 0;
		border: 0;
		background: rgb(10 16 30 / 0.28);
		cursor: default;
	}
	.sheet {
		position: relative;
		width: min(520px, 100%);
		border-radius: 24px;
		padding: 10px;
		display: grid;
		gap: 6px;
		background: var(--surface);
	}
	.field {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 4px 12px;
		border-radius: 16px;
		background: var(--surface-2);
	}
	.field svg {
		fill: none;
		stroke: var(--text-2);
		stroke-width: 2;
		stroke-linecap: round;
	}
	.field input {
		flex: 1;
		border: 0;
		background: transparent;
		padding: 10px 0;
		font-size: 1rem;
		outline: none;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		max-height: 50vh;
		overflow-y: auto;
	}
	a {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 12px;
		padding: 10px 12px;
		border-radius: 14px;
		color: var(--text);
		text-decoration: none;
	}
	a.on {
		background: var(--sel);
		box-shadow: var(--sel-shadow);
	}
	a span {
		font-size: 0.82rem;
	}
	.none {
		padding: 12px;
	}
	.hint {
		margin: 2px 12px 4px;
		font-size: 0.76rem;
	}
</style>
