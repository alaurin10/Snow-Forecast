<script lang="ts">
	import { getHealth, getOverview, getRuns, type Health } from '../../lib/api';
	import { prefs, type BandName, type Theme } from '../../lib/prefs.svelte';
	import type { OverviewRow, RunOut } from '../../lib/types.gen';

	let health = $state<Health | null>(null);
	let runs = $state<RunOut[]>([]);
	let rows = $state<OverviewRow[]>([]);

	$effect(() => {
		getHealth()
			.then((h) => (health = h))
			.catch(() => {});
		getRuns(20)
			.then((r) => (runs = r))
			.catch(() => {});
		getOverview()
			.then((r) => (rows = r))
			.catch(() => {});
	});

	const ago = (iso: string | null | undefined): string => {
		if (!iso) return 'never';
		const m = Math.round((Date.now() - Date.parse(iso)) / 60000);
		if (m < 60) return `${m} min ago`;
		const h = Math.round(m / 60);
		return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`;
	};
	const when = (iso: string) =>
		new Date(iso).toLocaleString('en-US', {
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		});
	const todayUtc = new Date().toISOString().slice(0, 10);
	const usedToday = $derived(
		Math.round(
			runs
				.filter((r) => r.started_at.slice(0, 10) === todayUtc)
				.reduce((a, r) => a + r.api_weight, 0)
		)
	);
	const themes: [Theme, string][] = [
		['auto', 'Match device'],
		['light', 'Light'],
		['dark', 'Dark']
	];
	const bands: [BandName, string][] = [
		['base', 'Base'],
		['mid', 'Mid'],
		['summit', 'Summit']
	];
</script>

<svelte:head><title>More · Snow Watch</title></svelte:head>

<div class="grid">
	<section class="card">
		<h2>Settings</h2>
		<div class="row">
			<span>Units</span>
			<div class="seg" role="group" aria-label="Units">
				<button aria-pressed={prefs.units === 'imperial'} onclick={() => prefs.setUnits('imperial')}
					>in, °F, ft</button
				>
				<button aria-pressed={prefs.units === 'metric'} onclick={() => prefs.setUnits('metric')}
					>cm, °C, m</button
				>
			</div>
		</div>
		<div class="row">
			<span>Theme</span>
			<div class="seg" role="group" aria-label="Theme">
				{#each themes as [t, label] (t)}
					<button aria-pressed={prefs.theme === t} onclick={() => prefs.setTheme(t)}>{label}</button
					>
				{/each}
			</div>
		</div>
		<div class="row">
			<span>Default elevation</span>
			<div class="seg" role="group" aria-label="Default elevation">
				{#each bands as [b, label] (b)}
					<button aria-pressed={prefs.band === b} onclick={() => prefs.setBand(b)}>{label}</button>
				{/each}
			</div>
		</div>
		<p class="faint small">Settings are saved on this device only.</p>
		<h3>Put it on your home screen</h3>
		<p class="muted small">
			<strong>iPhone:</strong> open this site in Safari, tap Share, then “Add to Home Screen”.<br />
			<strong>Android:</strong> in Chrome, open the ⋮ menu and choose “Install app”.<br />
			It then opens like an app and shows the last forecast even without signal.
		</p>
	</section>

	<section class="card">
		<h2>Status</h2>
		{#if health}
			<p class="small">
				Data: <strong
					>{health.status === 'ok'
						? 'up to date'
						: health.status === 'stale'
							? 'out of date'
							: 'no data yet'}</strong
				>
				{#if health.last_run}· last run {ago(health.last_run.finished_at)}{/if}
				· Open-Meteo today ≈ <strong>{usedToday}</strong> of 10,000 calls
			</p>
		{/if}
		<h3>Locations</h3>
		<div class="table-wrap">
			<table class="data">
				<tbody>
					{#each rows as r (r.id)}
						<tr><td>{r.name}</td><td>{ago(r.generated_at)}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
		<h3>Recent runs</h3>
		<div class="table-wrap">
			<table class="data">
				<thead
					><tr><th>Started</th><th>Kind</th><th>Status</th><th>Errors</th><th>Calls</th></tr></thead
				>
				<tbody>
					{#each runs as r (r.id)}
						<tr class:bad={r.status === 'failed'}>
							<td>{when(r.started_at)}</td>
							<td>{r.kind}</td>
							<td>{r.status}</td>
							<td title={r.errors.join('\n')}>{r.errors.length}</td>
							<td>{Math.round(r.api_weight)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</section>
</div>

<style>
	.grid {
		display: grid;
		gap: 12px;
	}
	@media (min-width: 900px) {
		.grid {
			grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
			align-items: start;
		}
	}
	.row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
		margin: 0 0 10px;
	}
	h3 {
		font-size: 0.85rem;
		color: var(--text-2);
		margin: 16px 0 6px;
	}
	.small {
		font-size: 0.85rem;
	}
	tr.bad td {
		color: var(--temp);
	}
</style>
