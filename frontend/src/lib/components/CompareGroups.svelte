<!-- Compare: your saved groups (kept in this browser). Open one, start a new comparison,
     or, in Edit, rename, reorder and delete them (the page offers an undo for a delete). -->
<script lang="ts">
	import { MAX_NAME, type Group } from '../compare';

	interface Props {
		groups: Group[];
		/** The open group's name, if any. */
		current: string | null;
		nameOf: (id: string) => string;
		onopen: (g: Group) => void;
		onnew: () => void;
		/** Returns an error to show, or null when renamed. */
		onrename: (from: string, to: string) => string | null;
		onmove: (name: string, by: -1 | 1) => void;
		ondelete: (name: string) => void;
	}

	let { groups, current, nameOf, onopen, onnew, onrename, onmove, ondelete }: Props = $props();
	let editing = $state(false);
	let renaming = $state<string | null>(null);
	let draft = $state('');
	let error = $state<string | null>(null);

	const describe = (g: Group) => {
		const names = g.locs.map(nameOf);
		const head = names.slice(0, 3).join(', ');
		const more = names.length > 3 ? `, +${names.length - 3}` : '';
		return `${g.locs.length} ${g.locs.length === 1 ? 'location' : 'locations'}${names.length ? ': ' : ''}${head}${more}`;
	};
	const same = (a: string | null, b: string) =>
		!!a && a.toLocaleLowerCase() === b.toLocaleLowerCase();

	function startRename(g: Group) {
		renaming = g.name;
		draft = g.name;
		error = null;
	}
	function saveRename(e: SubmitEvent) {
		e.preventDefault();
		if (!renaming) return;
		const err = onrename(renaming, draft);
		if (err) error = err;
		else renaming = null;
	}
</script>

<div class="groups">
	<button class="new" onclick={onnew}>
		<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
			><path d="M12 5v14M5 12h14" /></svg
		>
		New comparison
	</button>

	{#if groups.length}
		<ul>
			{#each groups as g, i (g.name)}
				<li>
					{#if renaming === g.name}
						<form class="rename" onsubmit={saveRename}>
							<input
								bind:value={draft}
								maxlength={MAX_NAME}
								aria-label="New name for {g.name}"
								aria-invalid={error ? 'true' : undefined}
							/>
							<button class="small" type="submit">Save</button>
							<button class="small plain" type="button" onclick={() => (renaming = null)}
								>Cancel</button
							>
							{#if error}<p class="err" role="alert">{error}</p>{/if}
						</form>
					{:else}
						<button
							class="open"
							aria-current={same(current, g.name) ? 'true' : undefined}
							onclick={() => onopen(g)}
							disabled={editing}
						>
							<strong>{g.name}</strong>
							<small>{describe(g)}</small>
						</button>
						{#if editing}
							<div class="tools">
								<button class="small" onclick={() => startRename(g)} aria-label="Rename {g.name}"
									>Rename</button
								>
								<button
									class="small"
									onclick={() => onmove(g.name, -1)}
									disabled={i === 0}
									aria-label="Move {g.name} up">↑</button
								>
								<button
									class="small"
									onclick={() => onmove(g.name, 1)}
									disabled={i === groups.length - 1}
									aria-label="Move {g.name} down">↓</button
								>
								<button
									class="small danger"
									onclick={() => ondelete(g.name)}
									aria-label="Delete {g.name}">Delete</button
								>
							</div>
						{/if}
					{/if}
				</li>
			{/each}
		</ul>
		<button
			class="edit"
			aria-pressed={editing}
			onclick={() => ((editing = !editing), (renaming = null))}
			>{editing ? 'Done' : 'Edit groups'}</button
		>
	{:else}
		<p class="faint empty">
			No groups yet. Choose some locations, then “Save as group” to open them again later.
		</p>
	{/if}
	<p class="faint note">
		Groups are kept in this browser. Use “Copy link” to take one to another device.
	</p>
</div>

<style>
	.groups {
		display: grid;
		gap: 10px;
		min-width: 0;
	}
	.new {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		min-height: 44px;
		border: 0;
		border-radius: 999px;
		background: var(--surface-2);
		font-size: 0.9rem;
		font-weight: 600;
		cursor: pointer;
	}
	.new svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2.2;
		stroke-linecap: round;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 4px;
	}
	li {
		display: grid;
		gap: 6px;
	}
	.open {
		width: 100%;
		display: grid;
		gap: 2px;
		min-height: 52px;
		padding: 8px 12px;
		border: 0;
		border-radius: 14px;
		background: transparent;
		text-align: left;
		cursor: pointer;
	}
	.open:hover:not(:disabled) {
		background: var(--hover);
	}
	.open[aria-current='true'] {
		background: var(--sel);
		box-shadow: var(--sel-shadow);
	}
	.open:disabled {
		cursor: default;
	}
	.open strong {
		font-size: 0.95rem;
		font-weight: 600;
	}
	.open small {
		font-size: 0.78rem;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.tools,
	.rename {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		padding: 0 12px 6px;
	}
	.rename input {
		flex: 1 1 160px;
		min-height: 36px;
		padding: 0 12px;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
		color: var(--text);
		font: inherit;
	}
	.small {
		min-height: 34px;
		min-width: 40px;
		padding: 0 12px;
		border: 0;
		border-radius: 999px;
		background: var(--surface-2);
		font-size: 0.82rem;
		font-weight: 600;
		cursor: pointer;
	}
	.small:disabled {
		opacity: 0.35;
		cursor: default;
	}
	.small.plain {
		background: transparent;
		color: var(--text-2);
	}
	.small.danger {
		color: var(--warn-ink);
	}
	.err {
		flex-basis: 100%;
		margin: 0;
		font-size: 0.8rem;
		color: var(--warn-ink);
	}
	.edit {
		justify-self: start;
		min-height: 34px;
		padding: 0 14px;
		border: 0;
		border-radius: 999px;
		background: transparent;
		font-size: 0.84rem;
		font-weight: 600;
		color: var(--text-2);
		cursor: pointer;
	}
	.edit[aria-pressed='true'] {
		background: var(--sel);
		box-shadow: var(--sel-shadow);
		color: var(--text);
	}
	.empty,
	.note {
		margin: 0;
		font-size: 0.82rem;
	}
</style>
