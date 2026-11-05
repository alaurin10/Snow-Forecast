<script lang="ts">
	import '@fontsource/barlow-semi-condensed/500.css';
	import '@fontsource/barlow-semi-condensed/600.css';
	import '../lib/theme.css';
	import favicon from '../lib/assets/favicon.svg';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { prefs } from '../lib/prefs.svelte';
	import { session } from '../lib/session.svelte';
	import { getHealth, type Health } from '../lib/api';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
	let health = $state<Health | null>(null);

	$effect(() => {
		const root = document.documentElement;
		if (prefs.theme === 'auto') delete root.dataset.theme;
		else root.dataset.theme = prefs.theme;
	});

	$effect(() => {
		const on = () => (session.online = true);
		const off = () => (session.online = false);
		window.addEventListener('online', on);
		window.addEventListener('offline', off);
		const check = () =>
			getHealth()
				.then((h) => (health = h))
				.catch(() => {});
		check();
		const timer = setInterval(check, 10 * 60 * 1000);
		return () => {
			window.removeEventListener('online', on);
			window.removeEventListener('offline', off);
			clearInterval(timer);
		};
	});

	const path = $derived(page.url.pathname);
	const tabs = [
		{ href: '/', label: 'Overview', icon: 'M4 6h16M4 12h16M4 18h10' },
		{ href: '/calendar', label: 'Calendar', icon: 'M4 6h16v14H4zM4 10h16M9 3v4M15 3v4' },
		{ href: '/plan', label: 'Plan', icon: 'M3 20l6-14 4 8 3-5 5 11zM9 6l2 4' },
		{ href: '/more', label: 'More', icon: 'M5 12h.01M12 12h.01M19 12h.01' }
	] as const;
	const active = (href: string) =>
		href === '/' ? path === '/' || path.startsWith('/location') : path.startsWith(href);
	const staleHours = $derived(
		health?.status === 'stale' && health.age_s ? Math.round(health.age_s / 3600) : null
	);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<meta name="theme-color" content="#2a78d6" />
</svelte:head>

<header class="bar">
	<a class="brand" href={resolve('/')}>Snow Watch</a>
	<nav class="topnav" aria-label="Main">
		{#each tabs as t (t.href)}
			<a href={resolve(t.href)} aria-current={active(t.href) ? 'page' : undefined}>{t.label}</a>
		{/each}
	</nav>
	<div class="controls">
		<div class="seg" role="group" aria-label="Units">
			<button aria-pressed={prefs.units === 'imperial'} onclick={() => prefs.setUnits('imperial')}
				>in °F</button
			>
			<button aria-pressed={prefs.units === 'metric'} onclick={() => prefs.setUnits('metric')}
				>cm °C</button
			>
		</div>
	</div>
</header>

{#if session.signInNeeded}
	<div class="banner warn" role="alert">
		Your sign-in has expired.
		<button onclick={() => location.reload()}>Sign in again</button>
	</div>
{:else if !session.online}
	<div class="banner">Offline: showing the forecast saved on this device.</div>
{:else if staleHours !== null}
	<div class="banner warn">
		The forecast hasn't updated for {staleHours} hours. <a href={resolve('/more')}>Status</a>
	</div>
{:else if health?.status === 'no_data'}
	<div class="banner">No forecast yet: the first run hasn't finished.</div>
{/if}

<main>
	{@render children()}
</main>

<footer class="faint">
	Weather data by <a href="https://open-meteo.com/">Open-Meteo.com</a> (CC BY 4.0), NWS, NRCS SNOTEL.
	Model snowfall is derived, not measured.
</footer>

<nav class="tabbar" aria-label="Main">
	{#each tabs as t (t.href)}
		<a href={resolve(t.href)} aria-current={active(t.href) ? 'page' : undefined}>
			<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d={t.icon} /></svg>
			<span>{t.label}</span>
		</a>
	{/each}
</nav>

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
	.topnav {
		display: none;
		gap: 4px;
		margin-right: auto;
		margin-left: 18px;
	}
	.topnav a {
		color: var(--text-2);
		text-decoration: none;
		padding: 6px 10px;
		border-radius: 8px;
	}
	.topnav a[aria-current='page'] {
		color: var(--text);
		background: var(--surface-2);
		font-weight: 600;
	}
	.banner {
		max-width: 1280px;
		margin: 10px auto 0;
		padding: 8px 14px;
		border-radius: 10px;
		background: var(--surface-2);
		border: 1px solid var(--border);
		font-size: 0.88rem;
		width: calc(100% - 32px);
	}
	.banner.warn {
		border-color: var(--temp);
	}
	.banner button {
		margin-left: 8px;
		border: 1px solid var(--border);
		background: var(--surface);
		border-radius: 999px;
		padding: 3px 10px;
		cursor: pointer;
	}
	.banner a {
		color: inherit;
	}
	main {
		max-width: 1280px;
		margin: 0 auto;
		padding: 12px 16px 24px;
	}
	footer {
		max-width: 1280px;
		margin: 0 auto;
		padding: 8px 16px 96px;
		font-size: 0.78rem;
	}
	footer a {
		color: inherit;
	}
	.tabbar {
		position: fixed;
		left: 0;
		right: 0;
		bottom: 0;
		z-index: 30;
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		background: var(--surface);
		border-top: 1px solid var(--border);
		padding-bottom: env(safe-area-inset-bottom);
	}
	.tabbar a {
		display: grid;
		justify-items: center;
		gap: 1px;
		padding: 7px 0 6px;
		color: var(--text-3);
		text-decoration: none;
		font-size: 0.72rem;
	}
	.tabbar svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.tabbar a[aria-current='page'] {
		color: var(--snow);
		font-weight: 600;
	}
	@media (min-width: 1100px) {
		.topnav {
			display: flex;
		}
		.tabbar {
			display: none;
		}
		footer {
			padding-bottom: 28px;
		}
	}
</style>
