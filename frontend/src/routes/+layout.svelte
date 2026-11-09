<script lang="ts">
	import '@fontsource/inter/400.css';
	import '@fontsource/inter/500.css';
	import '@fontsource/inter/600.css';
	import '@fontsource/space-grotesk/500.css';
	import '@fontsource/space-grotesk/600.css';
	import '../lib/theme.css';
	import favicon from '../lib/assets/favicon.svg';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { prefs } from '../lib/prefs.svelte';
	import { session } from '../lib/session.svelte';
	import { pageBar } from '../lib/pagebar.svelte';
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
		{ href: '/map', label: 'Map', icon: 'M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14' },
		{ href: '/calendar', label: 'Calendar', icon: 'M4 6h16v14H4zM4 10h16M9 3v4M15 3v4' },
		{ href: '/more', label: 'More', icon: 'M5 12h.01M12 12h.01M19 12h.01' }
	] as const;
	const active = (href: string) =>
		href === '/' ? path === '/' || path.startsWith('/location') : path.startsWith(href);
	// A page's controls take the nav's place once its own copy scrolls away.
	const docked = $derived(pageBar.show && !!pageBar.snippet);
	const staleHours = $derived(
		health?.status === 'stale' && health.age_s ? Math.round(health.age_s / 3600) : null
	);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<meta name="theme-color" content="#faf7f4" media="(prefers-color-scheme: light)" />
	<meta name="theme-color" content="#0a111d" media="(prefers-color-scheme: dark)" />
</svelte:head>

<header class="bar">
	<div class="bar-in">
		<a class="brand" href={resolve('/')}>
			<span class="mark" aria-hidden="true">
				<svg viewBox="0 0 24 24" width="19" height="19"
					><path
						d="M12 2v20M4.9 6.5l14.2 11M19.1 6.5L4.9 17.5M9.5 3.5L12 6l2.5-2.5M9.5 20.5L12 18l2.5 2.5"
					/></svg
				>
			</span>
			Snow Watch
		</a>
		<div class="center">
			<nav class="topnav glass" class:away={docked} aria-label="Main" inert={docked}>
				{#each tabs as t (t.href)}
					<a href={resolve(t.href)} aria-current={active(t.href) ? 'page' : undefined}>{t.label}</a>
				{/each}
			</nav>
			{#if pageBar.snippet}
				<div class="pagebar glass" class:on={docked} inert={!docked}>
					{@render pageBar.snippet()}
				</div>
			{/if}
		</div>
		<div class="seg glass units" role="group" aria-label="Units">
			<button aria-pressed={prefs.units === 'imperial'} onclick={() => prefs.setUnits('imperial')}
				>in · °F</button
			>
			<button aria-pressed={prefs.units === 'metric'} onclick={() => prefs.setUnits('metric')}
				>cm · °C</button
			>
		</div>
	</div>
</header>

{#if !session.online}
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

<nav class="tabbar glass" aria-label="Main">
	{#each tabs as t (t.href)}
		<a href={resolve(t.href)} aria-current={active(t.href) ? 'page' : undefined}>
			<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d={t.icon} /></svg>
			<span>{t.label}</span>
		</a>
	{/each}
</nav>

<style>
	.bar {
		position: sticky;
		top: 0;
		z-index: 30;
		background: var(--header-glass);
		backdrop-filter: blur(20px) saturate(1.6);
		-webkit-backdrop-filter: blur(20px) saturate(1.6);
		border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
	}
	.bar-in {
		max-width: 1280px;
		margin: 0 auto;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 16px;
		padding: 10px 16px;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 10px;
		font-family: var(--font-num);
		font-weight: 600;
		font-size: 1.15rem;
		color: var(--text);
		text-decoration: none;
		letter-spacing: -0.01em;
	}
	.mark {
		width: 32px;
		height: 32px;
		border-radius: 10px;
		background: var(--accent);
		display: grid;
		place-items: center;
	}
	.mark svg {
		fill: none;
		stroke: var(--surface);
		stroke-width: 2;
		stroke-linecap: round;
	}
	:global(.glass) {
		background: var(--glass);
		backdrop-filter: blur(24px) saturate(1.8);
		-webkit-backdrop-filter: blur(24px) saturate(1.8);
		border: 1px solid var(--glass-border);
		box-shadow: var(--glass-shadow);
	}
	.units {
		padding: 3px;
	}
	.units button {
		padding: 7px 12px;
	}
	.center {
		display: none;
	}
	.topnav,
	.pagebar {
		grid-area: 1 / 1;
		display: flex;
		gap: 2px;
		padding: 4px;
		border-radius: 999px;
		transition:
			opacity 0.28s ease,
			transform 0.28s ease,
			visibility 0.28s;
	}
	.topnav.away {
		opacity: 0;
		transform: translateY(-10px) scale(0.98);
		visibility: hidden;
	}
	.pagebar {
		opacity: 0;
		transform: translateY(10px) scale(0.98);
		visibility: hidden;
		padding: 4px 6px;
	}
	.pagebar.on {
		opacity: 1;
		transform: none;
		visibility: visible;
	}
	@media (prefers-reduced-motion: reduce) {
		.topnav,
		.pagebar {
			transition: none;
		}
	}
	.topnav a {
		color: var(--text-2);
		text-decoration: none;
		padding: 8px 18px;
		border-radius: 999px;
		font-size: 0.9rem;
	}
	.topnav a[aria-current='page'] {
		color: var(--accent);
		background: var(--surface);
		font-weight: 600;
		box-shadow: 0 2px 8px rgb(31 27 46 / 0.1);
	}
	.banner {
		max-width: 1248px;
		margin: 12px auto 0;
		padding: 10px 14px;
		border-radius: 14px;
		background: var(--surface-2);
		border: 1px solid var(--border);
		font-size: 0.88rem;
		width: calc(100% - 32px);
	}
	.banner.warn {
		background: var(--warn-bg);
		border-color: var(--warn-border);
	}
	.banner a {
		color: inherit;
	}
	main {
		max-width: 1280px;
		margin: 0 auto;
		padding: 16px 16px 24px;
	}
	footer {
		max-width: 1280px;
		margin: 0 auto;
		padding: 8px 16px 120px;
		font-size: 0.78rem;
	}
	footer a {
		color: inherit;
	}
	/* Phones and tablets: a floating glass pill. */
	.tabbar {
		position: fixed;
		left: 16px;
		right: 16px;
		bottom: calc(14px + env(safe-area-inset-bottom));
		z-index: 30;
		max-width: 440px;
		margin: 0 auto;
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 2px;
		padding: 5px;
		border-radius: 999px;
	}
	.tabbar a {
		display: grid;
		justify-items: center;
		gap: 2px;
		padding: 7px 0 6px;
		border-radius: 999px;
		color: var(--text-2);
		text-decoration: none;
		font-size: 0.68rem;
	}
	.tabbar svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.tabbar a[aria-current='page'] {
		color: var(--accent);
		background: var(--glass-active);
		font-weight: 600;
	}
	@media (min-width: 1100px) {
		.bar-in {
			padding: 12px 32px;
		}
		main {
			padding: 24px 32px;
		}
		footer {
			padding: 8px 32px 28px;
		}
		.center {
			display: grid;
			justify-items: center;
			align-items: center;
		}
		.tabbar {
			display: none;
		}
	}
	/* Phones: no brand bar. Every pixel above the fold is the page's; units live under More. */
	@media (max-width: 640px) {
		.bar {
			display: none;
		}
		main {
			padding-top: calc(12px + env(safe-area-inset-top));
		}
	}
</style>
