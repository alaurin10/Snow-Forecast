<script lang="ts">
	// Save the map around each forecast location for use with no signal.
	import { onMount } from 'svelte';
	import {
		available,
		downloadArea,
		estimateBytes,
		formatBytes,
		RADIUS_KM,
		removeArea,
		savedAreas,
		type Progress,
		type SavedArea
	} from '../offlineMaps';

	interface Place {
		id: string;
		name: string;
		lat: number;
		lon: number;
	}
	let { places, onclose }: { places: Place[]; onclose: () => void } = $props();

	let saved = $state<Record<string, SavedArea>>({});
	let busy = $state<string | null>(null);
	let progress = $state<Progress | null>(null);
	let error = $state<string | null>(null);
	let used = $state<number | null>(null);
	let free = $state<number | null>(null);
	let abort: AbortController | null = null;
	const ok = available();

	async function measure() {
		const est = await navigator.storage?.estimate?.().catch(() => undefined);
		used = est?.usage ?? null;
		free = est?.quota != null && est.usage != null ? est.quota - est.usage : null;
	}

	onMount(() => {
		saved = savedAreas();
		void measure();
		return () => abort?.abort();
	});

	async function save(p: Place) {
		if (busy) return;
		error = null;
		busy = p.id;
		progress = null;
		abort = new AbortController();
		try {
			let failed = 0;
			const r = await downloadArea(
				p,
				(x) => {
					progress = x;
					failed = x.failed;
				},
				abort.signal
			);
			saved = { ...saved, [p.id]: r };
			if (failed) error = `${failed} map pieces didn't download. Tap Update to try them again.`;
		} catch (e) {
			if ((e as Error).name !== 'AbortError')
				error = "Couldn't save this area. Check the connection.";
		} finally {
			busy = null;
			progress = null;
			abort = null;
			void measure();
		}
	}

	async function saveAll() {
		for (const p of places) {
			if (saved[p.id] && Date.now() - saved[p.id].at < 7 * 86400_000) continue;
			await save(p);
			if (error && !saved[p.id]) break;
		}
	}

	async function remove(p: Place) {
		if (busy) return;
		await removeArea(p.id);
		const rest = { ...saved };
		delete rest[p.id];
		saved = rest;
		void measure();
	}

	const ago = (t: number) => {
		const d = Math.floor((Date.now() - t) / 86400_000);
		return d < 1 ? 'today' : d === 1 ? 'yesterday' : `${d} days ago`;
	};
	const pct = $derived(
		progress ? Math.round((progress.done / Math.max(progress.total, 1)) * 100) : 0
	);
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onclose()} />

<div class="offline" role="dialog" aria-label="Offline maps">
	<div class="head">
		<strong>Offline maps</strong>
		<button class="close" onclick={onclose}>Close</button>
	</div>
	{#if !ok}
		<p>This browser can't save maps. On iPhone, use Safari or the app on your home screen.</p>
	{:else}
		<p class="faint">
			Saves the topo map, 3D terrain and ski runs for about {RADIUS_KM * 2} km around each location, so
			the Map works with no signal. Satellite and precipitation still need a connection.
		</p>
		<ul>
			{#each places as p (p.id)}
				{@const s = saved[p.id]}
				<li>
					<div class="name">
						<span>{p.name}</span>
						<span class="faint">
							{#if busy === p.id && progress}
								{pct}% · {formatBytes(progress.bytes)}
							{:else if s}
								Saved {ago(s.at)} · {formatBytes(s.bytes)}
							{:else}
								About {formatBytes(estimateBytes(p.lat, p.lon))}
							{/if}
						</span>
					</div>
					{#if busy === p.id}
						<button class="act" onclick={() => abort?.abort()}>Cancel</button>
					{:else if s}
						<button class="act" disabled={!!busy} onclick={() => save(p)}>Update</button>
						<button class="act quiet" disabled={!!busy} onclick={() => remove(p)}>Remove</button>
					{:else}
						<button class="act" disabled={!!busy} onclick={() => save(p)}>Save</button>
					{/if}
					{#if busy === p.id}
						<div
							class="bar"
							role="progressbar"
							aria-valuenow={pct}
							aria-valuemin={0}
							aria-valuemax={100}
						>
							<span style:width="{pct}%"></span>
						</div>
					{/if}
				</li>
			{/each}
		</ul>
		{#if error}<p class="err">{error}</p>{/if}
		<div class="foot">
			<span class="faint">
				{#if used != null}On this device: {formatBytes(used)}{#if free != null}, {formatBytes(free)} free{/if}{/if}
			</span>
			{#if places.length > 1}
				<button class="act" disabled={!!busy} onclick={saveAll}>Save all</button>
			{/if}
		</div>
		<p class="faint">Keep this page open while it saves. Updating only fetches what's missing.</p>
	{/if}
</div>

<style>
	.offline {
		position: absolute;
		top: 112px;
		left: calc(var(--map-inset, 0px) + 54px);
		right: 10px;
		max-width: 380px;
		max-height: calc(100% - 130px);
		overflow-y: auto;
		z-index: 1001;
		padding: 12px 14px;
		border-radius: 14px;
		background: var(--surface);
		border: 1px solid var(--border);
		box-shadow: var(--glass-shadow);
		font-size: 0.8rem;
		color: var(--text);
		display: grid;
		gap: 8px;
	}
	p {
		margin: 0;
	}
	.faint {
		color: var(--text-2);
	}
	.head,
	.foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 6px;
	}
	li {
		display: grid;
		grid-template-columns: 1fr auto auto;
		align-items: center;
		gap: 6px;
		padding: 6px 0;
		border-top: 1px solid var(--border);
	}
	.name {
		display: grid;
		min-width: 0;
	}
	.name span:first-child {
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.bar {
		grid-column: 1 / -1;
		height: 4px;
		border-radius: 2px;
		background: var(--border);
		overflow: hidden;
	}
	.bar span {
		display: block;
		height: 100%;
		background: var(--accent);
		transition: width 0.2s;
	}
	.act {
		border: 1px solid var(--accent);
		background: var(--accent);
		color: var(--on-accent);
		border-radius: 999px;
		padding: 4px 10px;
		font: inherit;
		font-weight: 600;
		cursor: pointer;
	}
	.act.quiet {
		background: transparent;
		color: var(--accent);
	}
	.act:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.close {
		border: 0;
		background: transparent;
		color: var(--accent);
		font-weight: 600;
		cursor: pointer;
		padding: 2px 4px;
	}
	.err {
		color: var(--warn-ink, var(--warn));
	}
</style>
