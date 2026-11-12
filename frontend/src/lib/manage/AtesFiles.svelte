<!--
  The owner's ATES files for the map: Avalanche Canada's trip planner offers each area's
  terrain ratings as a KMZ download (behind its own disclaimer). Upload one here and the
  map's "ATES terrain ratings" layer draws it; each file shows what it holds by rating,
  or why it can't be read.
-->
<script lang="ts">
	import { adminOverlays, deleteOverlay, putOverlay } from '../api';
	import { friendlyError } from '../errors';
	import type { OverlayFile } from '../types.gen';

	let files = $state<OverlayFile[] | null>(null);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let input = $state<HTMLInputElement>();

	const ORDER = ['non', 'simple', 'challenging', 'complex', 'extreme', 'unrated'];
	const WORDS: Record<string, string> = {
		non: 'non-avalanche',
		simple: 'simple',
		challenging: 'challenging',
		complex: 'complex',
		extreme: 'extreme',
		unrated: 'unrated'
	};

	async function load() {
		try {
			files = await adminOverlays();
		} catch (e) {
			error = friendlyError(e);
		}
	}
	$effect(() => {
		void load();
	});

	async function upload(file: File) {
		busy = true;
		error = null;
		try {
			await putOverlay(file);
			await load();
		} catch (e) {
			error = friendlyError(e);
		} finally {
			busy = false;
		}
	}

	async function remove(name: string) {
		if (!confirm(`Remove ${name} from the map?`)) return;
		busy = true;
		error = null;
		try {
			await deleteOverlay(name);
			await load();
		} catch (e) {
			error = friendlyError(e);
		} finally {
			busy = false;
		}
	}

	const summary = (f: OverlayFile) =>
		ORDER.filter((r) => f.ratings[r])
			.map((r) => `${f.ratings[r]} ${WORDS[r]}`)
			.join(', ');
	const kb = (n: number) => (n < 1e6 ? `${Math.round(n / 1000)} KB` : `${(n / 1e6).toFixed(1)} MB`);
</script>

<section class="card ates" aria-label="ATES terrain ratings">
	<h2>ATES terrain ratings</h2>
	<p class="faint small">
		Download an area's ratings (KMZ) from Avalanche Canada's trip planner and add it here: the map
		then offers them as a layer, as published. KML and GeoJSON work too.
	</p>
	{#if error}<p class="bad small" role="alert">{error}</p>{/if}
	{#if files?.length}
		<ul>
			{#each files as f (f.name)}
				<li>
					<div>
						<strong>{f.name}</strong>
						<span class="faint small">
							{kb(f.bytes)} ·
							{#if f.error}<em class="bad">{f.error}</em>{:else}{f.features} shapes: {summary(
									f
								)}{/if}
						</span>
					</div>
					<button class="btn small" disabled={busy} onclick={() => remove(f.name)}>Remove</button>
				</li>
			{/each}
		</ul>
	{:else if files}
		<p class="small">None yet.</p>
	{/if}
	<div>
		<button class="btn small" disabled={busy} onclick={() => input?.click()}
			>{busy ? 'Working…' : 'Add a file…'}</button
		>
		<input
			bind:this={input}
			type="file"
			accept=".kmz,.kml,.geojson,.json"
			hidden
			onchange={(e) => {
				const f = e.currentTarget.files?.[0];
				if (f) void upload(f);
				e.currentTarget.value = '';
			}}
		/>
	</div>
</section>

<style>
	.ates {
		display: grid;
		gap: 8px;
		margin-top: 16px;
	}
	h2 {
		margin: 0;
		font-size: 1rem;
	}
	p {
		margin: 0;
	}
	.small {
		font-size: 0.85rem;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 6px;
	}
	li {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}
	li div {
		display: grid;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.bad {
		color: var(--temp);
	}
</style>
