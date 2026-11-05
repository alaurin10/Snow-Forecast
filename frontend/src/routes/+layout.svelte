<script lang="ts">
	import '@fontsource/barlow-semi-condensed/500.css';
	import '@fontsource/barlow-semi-condensed/600.css';
	import '../lib/theme.css';
	import favicon from '../lib/assets/favicon.svg';
	import { prefs } from '../lib/prefs.svelte';
	import { resolve } from '$app/paths';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	$effect(() => {
		const root = document.documentElement;
		if (prefs.theme === 'auto') delete root.dataset.theme;
		else root.dataset.theme = prefs.theme;
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<meta name="theme-color" content="#2a78d6" />
</svelte:head>

<header class="bar">
	<a class="brand" href={resolve('/')}>Snow Watch</a>
	<div class="controls">
		<div class="seg" role="group" aria-label="Units">
			<button aria-pressed={prefs.units === 'imperial'} onclick={() => prefs.setUnits('imperial')}
				>in °F</button
			>
			<button aria-pressed={prefs.units === 'metric'} onclick={() => prefs.setUnits('metric')}
				>cm °C</button
			>
		</div>
		<button
			class="theme"
			aria-label={`Theme: ${prefs.theme}`}
			title={`Theme: ${prefs.theme}`}
			onclick={() =>
				prefs.setTheme(prefs.theme === 'auto' ? 'dark' : prefs.theme === 'dark' ? 'light' : 'auto')}
		>
			{prefs.theme === 'dark' ? '☾' : prefs.theme === 'light' ? '☀' : '◐'}
		</button>
	</div>
</header>

<main>
	{@render children()}
</main>

<footer class="faint">
	Weather data by <a href="https://open-meteo.com/">Open-Meteo.com</a> (CC BY 4.0), NWS, NRCS SNOTEL.
	Model snowfall is derived, not measured.
</footer>

<style>
	.bar {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
		padding: 10px 16px;
		background: var(--surface);
		border-bottom: 1px solid var(--border);
	}
	.brand {
		font-family: var(--font-num);
		font-weight: 600;
		font-size: 1.2rem;
		color: var(--text);
		text-decoration: none;
		letter-spacing: 0.01em;
	}
	.controls {
		display: flex;
		gap: 8px;
		align-items: center;
	}
	.theme {
		border: 1px solid var(--border);
		background: var(--surface-2);
		border-radius: 999px;
		width: 32px;
		height: 32px;
		cursor: pointer;
	}
	main {
		max-width: 1280px;
		margin: 0 auto;
		padding: 12px 16px 24px;
	}
	footer {
		max-width: 1280px;
		margin: 0 auto;
		padding: 8px 16px 28px;
		font-size: 0.78rem;
	}
	footer a {
		color: inherit;
	}
</style>
