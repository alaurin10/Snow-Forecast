<script lang="ts">
	import { resolve } from '$app/paths';
	import { getHealth, getMe, getMeta, getRuns, type Health } from '../../lib/api';
	import { friendlyError } from '../../lib/errors';
	import { ago } from '../../lib/time';
	import {
		prefs,
		THEME_FAMILIES,
		type BandName,
		type Motion,
		type Theme,
		type ThemeFamily
	} from '../../lib/prefs.svelte';
	import type { MetaOut, RunOut } from '../../lib/types.gen';
	import AlertsSettings from '../../lib/components/AlertsSettings.svelte';
	import { APP_VERSION, outOfDate, shortCommit } from '../../lib/version';

	let health = $state<Health | null>(null);
	let runs = $state<RunOut[]>([]);
	let meta = $state<MetaOut | null>(null);
	let metaFailed = $state(false);
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
			.catch(() => (metaFailed = true));
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
	const FAMILY: Record<ThemeFamily, { name: string; note: string }> = {
		sky: { name: 'Live Sky', note: 'The weather, live' },
		alpenglow: { name: 'Alpenglow', note: 'Rose and violet' },
		glacier: { name: 'Glacier', note: 'Ice blue' },
		larch: { name: 'Larch', note: 'Amber' },
		granite: { name: 'Granite', note: 'Patrol red' }
	};
	const motions: [Motion, string][] = [
		['full', 'Full'],
		['subtle', 'Subtle'],
		['off', 'Off']
	];
	const bands: [BandName, string][] = [
		['base', 'Base'],
		['mid', 'Mid'],
		['summit', 'Summit']
	];
</script>

<svelte:head><title>Settings · Snow Watch</title></svelte:head>

<header class="pagehead">
	<h1>Settings</h1>
	<p>Saved on this device only.</p>
</header>

{#if manage}
	<a class="card manage" href={resolve('/admin')}>
		<strong>Manage locations</strong>
		<span class="muted">Add resorts and backcountry zones, reorder, pause or remove them.</span>
	</a>
{/if}

<div class="grid">
	<section class="card wide" aria-labelledby="look-title">
		<h2 id="look-title">Appearance</h2>
		<div class="row">
			<span>Mode</span>
			<div class="seg" role="group" aria-label="Mode">
				{#each themes as [t, label] (t)}
					<button aria-pressed={prefs.theme === t} onclick={() => prefs.setTheme(t)}>{label}</button
					>
				{/each}
			</div>
		</div>
		<div class="field">
			<span id="theme-label">Theme</span>
			<div class="families" role="group" aria-labelledby="theme-label">
				{#each THEME_FAMILIES as f (f)}
					<button
						class="family"
						aria-pressed={prefs.themeFamily === f}
						onclick={() => prefs.setThemeFamily(f)}
					>
						<i class="swatch s-{f}" aria-hidden="true"></i>
						<strong>{FAMILY[f].name}</strong>
						<small>{FAMILY[f].note}</small>
					</button>
				{/each}
			</div>
		</div>
		<div class="row">
			<span>Motion</span>
			<div class="seg" role="group" aria-label="Motion">
				{#each motions as [m, label] (m)}
					<button aria-pressed={prefs.motion === m} onclick={() => prefs.setMotion(m)}
						>{label}</button
					>
				{/each}
			</div>
		</div>
		<p class="faint small hint">
			Subtle keeps the slow clouds but drops the falling snow. Off stops all movement. Your device’s
			reduce-motion setting always wins.
		</p>
	</section>

	<section class="card" aria-labelledby="forecast-title">
		<h2 id="forecast-title">Forecast</h2>
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
			<span>Default elevation</span>
			<div class="seg" role="group" aria-label="Default elevation">
				{#each bands as [b, label] (b)}
					<button aria-pressed={prefs.band === b} onclick={() => prefs.setBand(b)}>{label}</button>
				{/each}
			</div>
		</div>
		<div class="row">
			<span>Day timeline under the chart</span>
			<div class="seg" role="group" aria-label="Day timeline under the chart">
				<button
					aria-pressed={prefs.showTimeline === 'on'}
					onclick={() => prefs.setShowTimeline(true)}>Show</button
				>
				<button
					aria-pressed={prefs.showTimeline === 'off'}
					onclick={() => prefs.setShowTimeline(false)}>Hide</button
				>
			</div>
		</div>
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
	</section>

	<section class="card version" aria-labelledby="version-title">
		<h2 id="version-title">Version</h2>
		<p class="big">Snow Watch <span class="num">{APP_VERSION}</span></p>
		<dl class="small">
			<dt>This app</dt>
			<dd class="num">{APP_VERSION}</dd>
			<dt>Server</dt>
			<dd class="num">
				{#if meta}
					{meta.version}{#if shortCommit(meta.commit)}
						<span class="faint">· build {shortCommit(meta.commit)}</span>{/if}
				{:else if metaFailed}
					<span class="faint">unavailable</span>
				{:else}
					<span class="faint">checking…</span>
				{/if}
			</dd>
		</dl>
		{#if meta && outOfDate(meta.version)}
			<p class="small update" role="status">
				The server has version {meta.version}.
				<button class="btn small" onclick={() => location.reload()}>Reload to update</button>
			</p>
		{/if}
		<a class="btn" href={resolve('/about')}>About, data sources and privacy →</a>
	</section>
</div>

<style>
	.grid {
		display: grid;
		gap: 12px;
	}
	.version .big {
		font-family: var(--font-num);
		font-size: 1.15rem;
		font-weight: 600;
		margin: 0 0 6px;
	}
	.version dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 2px 12px;
		margin: 0 0 10px;
	}
	.version dt {
		color: var(--text-2);
	}
	.version dd {
		margin: 0;
	}
	.update {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	@media (min-width: 900px) {
		.grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
			align-items: start;
		}
		.wide {
			grid-column: 1 / -1;
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
		border-color: var(--accent);
	}
	.manage strong {
		color: var(--accent-ink);
	}
	.field {
		display: grid;
		gap: 8px;
		margin: 4px 0 14px;
	}
	.families {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
		gap: 8px;
	}
	.family {
		display: grid;
		gap: 2px;
		justify-items: start;
		text-align: left;
		padding: 8px 8px 10px;
		border: 1px solid var(--border);
		border-radius: 18px;
		background: var(--surface-2);
		cursor: pointer;
		transition:
			background-color var(--ease),
			box-shadow var(--ease);
	}
	.family:hover {
		background: var(--hover);
	}
	.family[aria-pressed='true'] {
		background: var(--sel);
		border-color: var(--accent);
		box-shadow:
			0 0 0 1px var(--accent),
			var(--sel-shadow);
	}
	.family strong {
		font-size: 0.86rem;
		font-weight: 600;
		margin-top: 6px;
	}
	.family small {
		font-size: 0.74rem;
		color: var(--text-2);
	}
	.swatch {
		display: block;
		width: 100%;
		height: 38px;
		border-radius: 12px;
		box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.06);
	}
	.s-sky {
		background:
			radial-gradient(circle at 78% 30%, #fff6c9 0 9%, transparent 10%),
			linear-gradient(160deg, #6f9fdc, #a9c8ee 55%, #e3eef9);
	}
	.s-alpenglow {
		background: linear-gradient(160deg, #6b4c8c, #c98aa6 55%, #f5dccd);
	}
	.s-glacier {
		background: linear-gradient(160deg, #2f5a8a, #9cc7ee 55%, #f5fafe);
	}
	.s-larch {
		background: linear-gradient(160deg, #8a6420, #e2b860 55%, #fbf6ea);
	}
	.s-granite {
		background: linear-gradient(160deg, #3d434d, #a7afb9 55%, #f5f6f8);
	}
	.hint {
		margin: -4px 0 0;
	}
</style>
