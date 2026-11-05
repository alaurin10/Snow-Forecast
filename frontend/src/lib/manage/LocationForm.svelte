<!-- Review and edit a location before saving (new from auto-detect, or existing). -->
<script lang="ts">
	import type { Location, SnotelCandidate } from '../types.gen';
	import { prefs } from '../prefs.svelte';

	interface Props {
		initial: Location;
		isNew: boolean;
		candidates?: SnotelCandidate[];
		warnings?: string[];
		avyName?: string | null;
		saving?: boolean;
		onsave: (loc: Location) => void;
		oncancel: () => void;
	}

	let {
		initial,
		isNew,
		candidates = [],
		warnings = [],
		avyName = null,
		saving = false,
		onsave,
		oncancel
	}: Props = $props();

	// A working copy the form edits. The Manage page mounts a fresh form for
	// each location, so copying `initial` once is intended.
	// svelte-ignore state_referenced_locally
	let loc = $state<Location>(structuredClone($state.snapshot(initial)) as Location);

	const imperial = $derived(prefs.units === 'imperial');
	const toShown = (m: number) => Math.round(imperial ? m * 3.28084 : m);
	const fromShown = (v: number) => (imperial ? v / 3.28084 : v);
	const elevs = $derived(loc.bands.map((b) => b.elev_m));
	const rising = $derived(elevs[0] < elevs[1] && elevs[1] < elevs[2]);
	const idOk = $derived(/^[a-z0-9][a-z0-9-]{1,39}$/.test(loc.id));
	const urlOk = (u: string | null | undefined) => !u || /^https?:\/\/\S+$/.test(u);
	const camsOk = $derived(
		(loc.webcams ?? []).every((w) => w.name.trim() && urlOk(w.url) && w.url && urlOk(w.image_url))
	);
	const canSave = $derived(rising && idOk && camsOk && loc.name.trim().length > 0 && !saving);
	function addCam() {
		loc.webcams = [...(loc.webcams ?? []), { name: '', url: '', image_url: null }];
	}

	function setElev(i: number, raw: string) {
		const v = Number(raw);
		if (Number.isFinite(v)) loc.bands[i].elev_m = Math.round(fromShown(v));
	}
	function setNum(i: number, key: 'lat' | 'lon', raw: string) {
		const v = Number(raw);
		if (Number.isFinite(v)) loc.bands[i][key] = v;
	}
</script>

<form
	class="form"
	onsubmit={(e) => {
		e.preventDefault();
		if (canSave) onsave($state.snapshot(loc) as Location);
	}}
>
	{#if warnings.length}
		<ul class="warn">
			{#each warnings as w (w)}<li>{w}</li>{/each}
		</ul>
	{/if}

	<div class="grid2">
		<label>Name <input bind:value={loc.name} required /></label>
		<label>
			ID (in the address)
			<input bind:value={loc.id} readonly={!isNew} pattern="[a-z0-9][a-z0-9\-]{'{1,39}'}" />
			{#if !idOk}<small class="bad">lowercase letters, numbers and dashes</small>{/if}
		</label>
		<label>Region <input bind:value={loc.region} placeholder="e.g. WA Cascades" /></label>
		<label>
			Kind
			<select bind:value={loc.kind}>
				<option value="resort">Resort</option>
				<option value="backcountry">Backcountry</option>
			</select>
		</label>
	</div>

	<h4>Elevation bands</h4>
	<div class="table-wrap">
		<table class="data bands">
			<thead>
				<tr
					><th>Band</th><th>Label</th><th>Elevation ({imperial ? 'ft' : 'm'})</th><th>Lat</th><th
						>Lon</th
					></tr
				>
			</thead>
			<tbody>
				{#each loc.bands as b, i (b.band)}
					<tr>
						<td>{b.band}</td>
						<td><input bind:value={b.label} /></td>
						<td
							><input
								type="number"
								value={toShown(b.elev_m)}
								onchange={(e) => setElev(i, e.currentTarget.value)}
							/></td
						>
						<td
							><input
								type="number"
								step="any"
								value={b.lat}
								onchange={(e) => setNum(i, 'lat', e.currentTarget.value)}
							/></td
						>
						<td
							><input
								type="number"
								step="any"
								value={b.lon}
								onchange={(e) => setNum(i, 'lon', e.currentTarget.value)}
							/></td
						>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	{#if !rising}<p class="bad">Elevations must rise from base to summit.</p>{/if}

	<h4>Detected</h4>
	<div class="grid2">
		<label>
			Snow station
			<select bind:value={loc.snotel}>
				<option value={null}>None</option>
				{#if loc.snotel && !candidates.some((c) => c.triplet === loc.snotel)}
					<option value={loc.snotel}>{loc.snotel}</option>
				{/if}
				{#each candidates as c (c.triplet)}
					<option value={c.triplet}>
						{c.name}: {c.distance_km} km, {c.elev_m === null ? '?' : toShown(c.elev_m)}
						{imperial ? 'ft' : 'm'}
					</option>
				{/each}
			</select>
		</label>
		<label>Timezone <input bind:value={loc.tz} /></label>
		<div class="ro">
			<span>Country</span><strong>{loc.country}</strong>
		</div>
		<div class="ro">
			<span>NWS office / radar</span><strong
				>{loc.nws_office ?? '–'} / {loc.radar_station ?? '–'}</strong
			>
		</div>
		<div class="ro">
			<span>Avalanche zone</span>
			<strong>
				{#if loc.avy?.provider === 'nac'}{loc.avy.center_id} · {avyName ?? loc.avy.zone_id}
				{:else if loc.avy?.provider === 'avcan'}Avalanche Canada (found by location)
				{:else}–{/if}
			</strong>
		</div>
		<label class="check"
			><input type="checkbox" bind:checked={loc.active} /> Active (fetch and show it)</label
		>
	</div>

	{#if Object.keys(loc.links ?? {}).length}
		<h4>Links</h4>
		<ul class="links">
			{#each Object.entries(loc.links ?? {}) as [name, url] (name)}
				<li>
					<span>{name}</span>
					<span class="faint url">{url}</span>
					<button
						type="button"
						class="x"
						aria-label={`Remove ${name}`}
						onclick={() => delete loc.links![name]}>✕</button
					>
				</li>
			{/each}
		</ul>
	{/if}

	<h4>Webcams</h4>
	{#each loc.webcams ?? [] as cam, i (i)}
		<div class="cam">
			<label>Name <input bind:value={cam.name} placeholder="e.g. Summit cam" /></label>
			<label
				>Page link <input
					bind:value={cam.url}
					type="url"
					placeholder="https://… (the webcam's web page)"
				/></label
			>
			<label
				>Image link (optional) <input
					value={cam.image_url ?? ''}
					oninput={(e) => (cam.image_url = e.currentTarget.value.trim() || null)}
					type="url"
					placeholder="https://… (a .jpg that updates)"
				/></label
			>
			<button
				type="button"
				class="x"
				aria-label={`Remove ${cam.name || 'webcam'}`}
				onclick={() => (loc.webcams = (loc.webcams ?? []).filter((_, j) => j !== i))}>✕</button
			>
		</div>
	{/each}
	{#if !camsOk}<p class="bad">Each webcam needs a name and links starting with https://</p>{/if}
	<button type="button" class="btn small addcam" onclick={addCam}>+ Add a webcam</button>

	<div class="actions">
		<button type="button" class="btn" onclick={oncancel}>Cancel</button>
		<button type="submit" class="btn primary" disabled={!canSave}>
			{saving ? 'Saving…' : isNew ? 'Add location' : 'Save changes'}
		</button>
	</div>
</form>

<style>
	.form {
		display: grid;
		gap: 10px;
	}
	.grid2 {
		display: grid;
		gap: 10px;
	}
	@media (min-width: 700px) {
		.grid2 {
			grid-template-columns: 1fr 1fr;
		}
	}
	label {
		display: grid;
		gap: 3px;
		font-size: 0.82rem;
		color: var(--text-2);
	}
	input,
	select {
		font: inherit;
		font-size: 0.95rem;
		color: var(--text);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 7px 9px;
		min-width: 0;
	}
	.bands input {
		width: 100%;
		min-width: 70px;
		padding: 5px 7px;
	}
	.bands td:first-child {
		color: var(--text-2);
	}
	.check {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--text);
	}
	.ro {
		display: grid;
		gap: 3px;
		font-size: 0.82rem;
		color: var(--text-2);
	}
	.ro strong {
		color: var(--text);
		font-size: 0.95rem;
		font-weight: 500;
	}
	h4 {
		margin: 6px 0 0;
		font-size: 0.85rem;
	}
	.warn {
		margin: 0;
		padding: 8px 12px 8px 26px;
		border: 1px solid var(--temp);
		border-radius: 8px;
		font-size: 0.85rem;
	}
	.bad {
		color: var(--temp);
		font-size: 0.82rem;
		margin: 0;
	}
	.links {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		gap: 4px;
		font-size: 0.85rem;
	}
	.links li {
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 8px;
		align-items: center;
		min-width: 0;
	}
	.url {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.x {
		border: 0;
		background: none;
		cursor: pointer;
		color: var(--text-3);
	}
	.cam {
		display: grid;
		gap: 6px;
		grid-template-columns: 1fr auto;
		align-items: end;
		padding: 8px 0;
		border-bottom: 1px solid var(--border);
	}
	.cam label {
		grid-column: 1;
	}
	.cam .x {
		grid-column: 2;
		grid-row: 1;
	}
	@media (min-width: 700px) {
		.cam {
			grid-template-columns: 1fr 1.5fr 1.5fr auto;
		}
		.cam label {
			grid-column: auto;
		}
		.cam .x {
			grid-column: auto;
			grid-row: auto;
		}
	}
	.addcam {
		justify-self: start;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 4px;
	}
</style>
