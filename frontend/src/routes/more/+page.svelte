<script lang="ts">
	import { resolve } from '$app/paths';
	import { getHealth, getMe, getMeta, getRuns, type Health } from '../../lib/api';
	import { friendlyError } from '../../lib/errors';
	import { ago } from '../../lib/time';
	import { prefs, type BandName, type Theme } from '../../lib/prefs.svelte';
	import type { MetaOut, RunOut } from '../../lib/types.gen';
	import AlertsSettings from '../../lib/components/AlertsSettings.svelte';

	let health = $state<Health | null>(null);
	let runs = $state<RunOut[]>([]);
	let meta = $state<MetaOut | null>(null);
	let manage = $state(false);
	let statusError = $state<string | null>(null);

	$effect(() => {
		getHealth()
			.then((h) => (health = h))
			.catch((e) => (statusError = friendlyError(e)));
		getRuns(50)
			.then((r) => (runs = r))
			.catch(() => {}); // the usage figure is optional
		getMeta()
			.then((m) => (meta = m))
			.catch(() => {}); // only the budget and version
		getMe()
			.then((m) => (manage = m.is_owner || m.owner_login_enabled))
			.catch(() => {}); // no Manage link when the server can't say
	});

	// Runs are stamped in UTC; count today's (UTC) calls.
	const usedToday = $derived.by(() => {
		const today = new Date().toISOString().slice(0, 10);
		return Math.round(
			runs.filter((r) => r.started_at.slice(0, 10) === today).reduce((a, r) => a + r.api_weight, 0)
		);
	});
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

{#if manage}
	<a class="card manage" href={resolve('/admin')}>
		<strong>Manage locations</strong>
		<span class="muted">Add resorts and backcountry zones, reorder, pause or remove them.</span>
	</a>
{/if}

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

	<AlertsSettings />

	<section class="card">
		<h2>Status</h2>
		{#if statusError}
			<p class="small muted" role="alert">{statusError}</p>
		{:else if !health}
			<p class="small muted" aria-live="polite">Loading…</p>
		{:else}
			<p class="small">
				Data: <strong
					>{health.status === 'ok'
						? 'up to date'
						: health.status === 'stale'
							? 'out of date'
							: 'no data yet'}</strong
				>
				{#if health.last_run}· last run {ago(health.last_run.finished_at)}{/if}
				{#if meta}· Open-Meteo today ≈ <strong>{usedToday.toLocaleString('en-US')}</strong> of
					{meta.open_meteo_daily_budget.toLocaleString('en-US')} calls{/if}
			</p>
		{/if}
		<a class="btn" href={resolve('/status')}>Sources, runs and data age →</a>
		<a class="btn" href={resolve('/about')}>About, data sources and privacy →</a>
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
	.manage {
		display: grid;
		gap: 2px;
		color: inherit;
		text-decoration: none;
		margin-bottom: 12px;
		border-color: var(--snow);
	}
</style>
