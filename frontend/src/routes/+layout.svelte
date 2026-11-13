<!-- The app shell. Behind everything, the sky (the weather now). On desktop a glass rail
     on the left holds the navigation and every location with its 5-day total; it sits in
     the same place on every page (over the map too) and never changes size. On phones and
     tablets a floating glass tab bar sits at the bottom and shrinks to icons while you
     scroll down. Notices float at the top as toasts, so nothing below them moves.
     Ctrl/⌘ K jumps to a location; [ and ] step through locations on a location page, and
     1–4 pick its section. -->
<script lang="ts">
	import '@fontsource/inter/400.css';
	import '@fontsource/inter/500.css';
	import '@fontsource/inter/600.css';
	import '@fontsource/manrope/400.css';
	import '@fontsource/manrope/500.css';
	import '@fontsource/manrope/600.css';
	import '@fontsource/manrope/700.css';
	import '../lib/theme.css';
	import favicon from '../lib/assets/favicon.svg';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { prefs } from '../lib/prefs.svelte';
	import { session } from '../lib/session.svelte';
	import { appUpdate } from '../lib/update.svelte';
	import { viewport } from '../lib/viewport.svelte';
	import { railUi } from '../lib/railui.svelte';
	import { sections } from '../lib/sections.svelte';
	import { skyState } from '../lib/skystate.svelte';
	import { skyOf } from '../lib/sky';
	import { snowNum } from '../lib/units';
	import { getHealth, getOverview, getSnapshot, type Health } from '../lib/api';
	import type { OverviewRow } from '../lib/types.gen';
	import Sky from '../lib/components/Sky.svelte';
	import LocationPalette from '../lib/components/LocationPalette.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
	let health = $state<Health | null>(null);
	let rows = $state<OverviewRow[]>([]);
	let palette = $state(false);

	// Colour mode, theme family and motion live on <html> (static/theme-init.js sets
	// them before the app starts; this keeps them in step with Settings and the device).
	let systemDark = $state(
		typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-color-scheme: dark)').matches
	);
	$effect(() => {
		const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
		if (!mq) return;
		const on = (e: MediaQueryListEvent) => (systemDark = e.matches);
		mq.addEventListener('change', on);
		return () => mq.removeEventListener('change', on);
	});
	const dark = $derived(prefs.theme === 'dark' || (prefs.theme === 'auto' && systemDark));
	$effect(() => {
		const root = document.documentElement;
		root.dataset.mode = dark ? 'dark' : 'light';
		if (prefs.themeFamily === 'sky') delete root.dataset.theme;
		else root.dataset.theme = prefs.themeFamily;
		if (prefs.motion === 'full') delete root.dataset.motion;
		else root.dataset.motion = prefs.motion;
	});

	$effect(() => appUpdate.watch());

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

	// Every location, for the rail and the palette; the first one's weather is the sky
	// on pages that aren't about one location.
	$effect(() => {
		getOverview()
			.then((r) => {
				rows = r;
				const first = r.find((x) => x.run_id != null);
				if (first)
					getSnapshot(first.id)
						.then((s) => (skyState.home = skyOf(s)))
						.catch(() => {});
			})
			.catch(() => {});
	});

	const path = $derived(page.url.pathname);
	const ICONS = {
		overview: 'M4 6h16M4 12h16M4 18h10',
		map: 'M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14',
		calendar: 'M4 6h16v14H4zM4 10h16M9 3v4M15 3v4',
		// A gear (Feather icons, MIT).
		settings:
			'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z'
	};
	// Phones and tablets: the thumb-reach order. Desktop: the rail's order.
	const tabs = [
		{ href: '/', label: 'Overview', icon: ICONS.overview },
		{ href: '/map', label: 'Map', icon: ICONS.map },
		{ href: '/calendar', label: 'Calendar', icon: ICONS.calendar },
		{ href: '/settings', label: 'Settings', icon: ICONS.settings }
	] as const;
	const railNav = [tabs[0], tabs[2], tabs[1], tabs[3]];
	/** Desktop map page: the map fills the window and the rail floats over it, foldable. */
	const overMap = $derived(viewport.desktop && page.route.id === '/map');
	const folded = $derived(overMap && railUi.folded);
	const active = (href: string) =>
		href === '/' ? path === '/' || path.startsWith('/location') : path.startsWith(href);
	const staleHours = $derived(
		health?.status === 'stale' && health.age_s ? Math.round(health.age_s / 3600) : null
	);
	const located = $derived(rows.filter((r) => r.run_id != null || r.periods?.length));
	// The notice showing, if any (one at a time, most pressing first), and the one closed.
	// The full map says it's offline itself ("showing saved maps").
	const notice = $derived(
		appUpdate.waiting
			? 'update'
			: !session.online && page.route.id !== '/map'
				? 'offline'
				: staleHours !== null
					? 'stale'
					: health?.status === 'no_data'
						? 'nodata'
						: null
	);
	let closed = $state<string | null>(null);

	// Phones and tablets: the tab bar shrinks to icons while you scroll down, and always on
	// the map, which doesn't scroll and wants the room. Its height stays the same, so the
	// map's controls above it never move.
	let compact = $state(false);
	const compactBar = $derived(compact || page.route.id === '/map');
	$effect(() => {
		let last = window.scrollY;
		const on = () => {
			const y = window.scrollY;
			if (y > last + 6 && y > 80) compact = true;
			else if (y < last - 6 || y < 40) compact = false;
			last = y;
		};
		window.addEventListener('scroll', on, { passive: true });
		return () => window.removeEventListener('scroll', on);
	});

	function onkey(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
			e.preventDefault();
			palette = !palette;
			return;
		}
		const typing = (e.target as HTMLElement | null)?.closest?.(
			'input, textarea, select, [contenteditable="true"]'
		);
		if (typing || e.metaKey || e.ctrlKey || e.altKey || palette) return;
		// 1–4: the open location's sections, in the order its tabs show them.
		if (sections.id && /^[1-9]$/.test(e.key)) {
			const s = sections.list[Number(e.key) - 1];
			if (s) sections.tab = s;
			return;
		}
		if ((e.key === '[' || e.key === ']') && sections.id && rows.length) {
			const ids = rows.map((r) => r.id);
			const at = ids.indexOf(sections.id);
			if (at < 0) return;
			const next = ids[(at + (e.key === ']' ? 1 : -1) + ids.length) % ids.length];
			void goto(resolve('/location/[id]', { id: next }));
		}
	}
</script>

<svelte:window onkeydown={onkey} />

<svelte:head>
	<link rel="icon" href={favicon} />
	<meta name="theme-color" content={dark ? '#1a2336' : '#e8f0f9'} />
</svelte:head>

<Sky />

<div class="app" class:withrail={viewport.desktop} class:overmap={overMap}>
	{#if viewport.desktop}
		<!-- Always in the page on desktop, so folding slides it away rather than swapping it
		     out; inert while folded. -->
		<aside class="rail glass" class:folded id="rail" aria-label="Navigation" inert={folded}>
			<div class="brandrow">
				<a class="brand" href={resolve('/')}>
					<span class="mark" aria-hidden="true">
						<svg viewBox="0 0 24 24" width="18" height="18"
							><path
								d="M12 2v20M4.9 6.5l14.2 11M19.1 6.5L4.9 17.5M9.5 3.5L12 6l2.5-2.5M9.5 20.5L12 18l2.5 2.5"
							/></svg
						>
					</span>
					Snow Watch
				</a>
				<!-- Its 32 px are kept on every page; it fades in on the map, where it works. -->
				<button
					class="fold"
					class:shown={overMap}
					onclick={() => railUi.setFolded(true)}
					tabindex={overMap ? 0 : -1}
					aria-hidden={overMap ? undefined : 'true'}
					aria-expanded="true"
					aria-controls="rail"
					aria-label="Hide navigation"
					title="Hide navigation: more room for the map"
				>
					<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
						><path d="M15 6l-6 6 6 6" /></svg
					>
				</button>
			</div>
			<nav class="railnav" aria-label="Main">
				{#each railNav as t (t.href)}
					<a
						href={resolve(t.href)}
						aria-current={active(t.href) && (t.href !== '/' || !sections.id) ? 'page' : undefined}
					>
						<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
							><path d={t.icon} /></svg
						>
						{t.label}
					</a>
				{/each}
			</nav>
			{#if located.length}
				<div class="railhead">
					<span>Locations</span><span class="unit"
						>5 days, {prefs.units === 'imperial' ? 'in' : 'cm'}</span
					>
				</div>
				<!-- The open location is only highlighted: its sections are the page's own tabs,
				     so this list never changes height. -->
				<ul class="locs">
					{#each located as r (r.id)}
						{@const open = sections.id === r.id}
						<li class:open>
							<a
								class="loc"
								href={resolve('/location/[id]', { id: r.id })}
								aria-current={open ? 'page' : undefined}
							>
								<span class="lname">{r.name}</span>
								<span class="ltot num" class:zero={!r.next5_cm}
									>{r.next5_cm == null ? '–' : snowNum(r.next5_cm, prefs.units)}</span
								>
							</a>
						</li>
					{/each}
				</ul>
			{/if}
			<button class="jump" onclick={() => (palette = true)}>
				<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
					><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg
				>
				<span>Jump to a location</span>
				<kbd>Ctrl K</kbd>
			</button>
		</aside>
		{#if overMap}
			<button
				class="railfold glass"
				class:shown={folded}
				inert={!folded}
				onclick={() => railUi.setFolded(false)}
				aria-expanded="false"
				aria-controls="rail"
				aria-label="Show navigation"
				title="Show navigation and locations"
			>
				<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"
					><path d="M4 6h16M4 12h16M4 18h16" /></svg
				>
			</button>
		{/if}
	{/if}

	<div class="col">
		<!-- Notices float at the top as a toast (they never push the page down); each can be
		     closed until a different one comes up. -->
		{#if notice && closed !== notice}
			<div
				class="banner"
				class:glass={notice !== 'stale'}
				class:warn={notice === 'stale'}
				role="status"
			>
				<span class="btxt">
					{#if notice === 'update'}
						A new version of Snow Watch is ready.
						<button class="btn small" onclick={() => appUpdate.apply()}>Reload</button>
					{:else if notice === 'offline'}
						Offline: showing the forecast saved on this device.
					{:else if notice === 'stale'}
						The forecast hasn't updated for {staleHours} hours.
						<a href={resolve('/status')}>Status</a>
					{:else}
						No forecast yet: the first run hasn't finished.
					{/if}
				</span>
				<button class="bclose" onclick={() => (closed = notice)} aria-label="Close notice">
					<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
						><path d="M6 6l12 12M18 6L6 18" /></svg
					>
				</button>
			</div>
		{/if}

		<main>
			{@render children()}
		</main>

		<!-- The map credits its sources in its own (i) corner. -->
		{#if page.route.id !== '/map'}
			<footer>
				<span class="glass"
					>Weather data by <a href="https://open-meteo.com/">Open-Meteo.com</a> (CC BY 4.0), NWS,
					NRCS SNOTEL and <a href={resolve('/about')}>others</a>. Model snowfall is derived, not
					measured; never a substitute for your avalanche center.</span
				>
			</footer>
		{/if}
	</div>
</div>

{#if !viewport.desktop}
	<nav class="tabbar glass" class:compact={compactBar} aria-label="Main">
		{#each tabs as t (t.href)}
			<a
				href={resolve(t.href)}
				aria-current={active(t.href) ? 'page' : undefined}
				aria-label={t.label}
			>
				<svg viewBox="0 0 24 24" width="21" height="21" aria-hidden="true"><path d={t.icon} /></svg>
				<span aria-hidden="true">{t.label}</span>
			</a>
		{/each}
	</nav>
{/if}

{#if palette}
	<LocationPalette
		locations={rows.map((r) => ({ id: r.id, name: r.name, region: r.region }))}
		onclose={() => (palette = false)}
	/>
{/if}

<style>
	.app {
		min-height: 100vh;
	}
	/* Desktop: the rail is fixed at the window's top left on every page; the page column
	   sits beside it, centred in the space that's left (up to 1140 px wide). */
	.app.withrail {
		padding-top: 14px;
	}
	.col {
		min-width: 0;
	}
	.withrail .col {
		max-width: 1140px;
		margin-left: max(282px, calc(282px + (100vw - 302px - 1140px) / 2));
		margin-right: 20px;
	}

	/* --- Desktop rail --- */
	/* One place on every page: 14 px from the top left, 248 px wide (RAIL_OPEN_INSET in
	   railui.svelte.ts follows this). Only its density changes over the map, and folding
	   slides it away. */
	.rail {
		position: fixed;
		top: 14px;
		left: 14px;
		z-index: 20;
		width: 248px;
		box-sizing: border-box;
		max-height: calc(100vh - 28px);
		overflow-y: auto;
		border-radius: 28px;
		padding: 14px 10px 12px;
		display: flex;
		flex-direction: column;
		gap: 4px;
		scrollbar-width: thin;
		transition:
			background-color 300ms ease,
			box-shadow 300ms ease,
			opacity 300ms cubic-bezier(0.2, 0.8, 0.2, 1),
			transform 300ms cubic-bezier(0.2, 0.8, 0.2, 1),
			visibility 0s;
	}
	.rail.folded {
		opacity: 0;
		transform: translateX(-24px) scale(0.97);
		transform-origin: top left;
		visibility: hidden;
		transition:
			background-color 300ms ease,
			box-shadow 300ms ease,
			opacity 300ms cubic-bezier(0.2, 0.8, 0.2, 1),
			transform 300ms cubic-bezier(0.2, 0.8, 0.2, 1),
			visibility 0s 300ms;
	}
	.brandrow {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 6px;
	}
	.fold {
		flex: 0 0 32px;
		width: 32px;
		height: 32px;
		margin: 2px 2px 0 0;
		opacity: 0;
		visibility: hidden;
		transition:
			opacity 300ms ease,
			visibility 0s 300ms,
			background-color var(--ease);
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 11px;
		background: transparent;
		color: var(--text-2);
		cursor: pointer;
	}
	.fold.shown {
		opacity: 1;
		visibility: visible;
		transition:
			opacity 300ms ease,
			visibility 0s,
			background-color var(--ease);
	}
	.fold:hover {
		background: var(--hover);
		color: var(--text);
	}
	.fold svg,
	.railfold svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	/* The desktop map page: the map takes the whole window (see MapView) and the rail
	   floats over its left side, or folds to this button. */
	.app.withrail.overmap {
		padding: 0;
	}
	.overmap .rail {
		/* Denser than over the sky: a busy map shows through otherwise. */
		background-color: color-mix(in srgb, var(--surface) 90%, transparent);
	}
	.withrail.overmap .col {
		max-width: none;
		margin: 0;
	}
	/* Folded: the first of the map's buttons, the same size, at the head of their column. */
	.railfold {
		position: fixed;
		top: 10px;
		left: 10px;
		z-index: 20;
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		border-radius: 14px;
		color: var(--text);
		cursor: pointer;
		background: color-mix(in srgb, var(--surface) 90%, transparent);
		opacity: 0;
		transform: scale(0.85);
		visibility: hidden;
		transition:
			opacity 250ms ease,
			transform 250ms ease,
			visibility 0s 250ms,
			background-color var(--ease);
	}
	.railfold.shown {
		opacity: 1;
		transform: none;
		visibility: visible;
		/* In once the rail has mostly gone. */
		transition:
			opacity 250ms ease 120ms,
			transform 250ms ease 120ms,
			visibility 0s 120ms,
			background-color var(--ease);
	}
	.railfold:hover {
		background-color: var(--hover);
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 2px 8px 10px;
		font-family: var(--font-num);
		font-weight: 700;
		font-size: 1.08rem;
		color: var(--text);
		text-decoration: none;
		letter-spacing: -0.01em;
	}
	.mark {
		width: 32px;
		height: 32px;
		border-radius: 11px;
		background: var(--accent);
		display: grid;
		place-items: center;
	}
	.mark svg {
		fill: none;
		stroke: var(--on-accent);
		stroke-width: 2;
		stroke-linecap: round;
	}
	.railnav {
		display: grid;
		gap: 2px;
	}
	.railnav a,
	.loc {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 40px;
		padding: 0 10px;
		border-radius: 14px;
		font-weight: 500;
		color: var(--text-2);
		text-decoration: none;
		transition: background-color var(--ease);
	}
	.railnav a:hover,
	.loc:hover {
		background: var(--hover);
	}
	/* Selection is colour and background only: a bolder weight would widen the text. */
	.railnav a[aria-current='page'] {
		background: var(--sel);
		box-shadow: var(--sel-shadow);
		color: var(--text);
	}
	.railnav svg,
	.jump svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 1.9;
		stroke-linecap: round;
		stroke-linejoin: round;
		flex-shrink: 0;
	}
	.railhead {
		display: flex;
		justify-content: space-between;
		padding: 14px 10px 4px;
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--text-3);
	}
	.railhead .unit {
		text-transform: none;
		letter-spacing: 0;
		font-weight: 500;
	}
	.locs {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 2px;
	}
	.locs li {
		min-width: 0;
		border-radius: 16px;
		transition:
			background-color var(--ease),
			box-shadow var(--ease);
	}
	.locs li.open {
		background: var(--sel);
		box-shadow: var(--sel-shadow);
	}
	.loc {
		min-height: 42px;
		color: var(--text);
	}
	.lname {
		flex: 1;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.ltot {
		font-weight: 600;
	}
	.ltot.zero {
		color: var(--text-3);
	}
	.jump {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 12px;
		min-height: 38px;
		padding: 0 10px;
		border: 0;
		border-radius: 14px;
		background: var(--surface-2);
		color: var(--text-2);
		font-size: 0.85rem;
		cursor: pointer;
		text-align: left;
	}
	.jump span {
		flex: 1;
	}
	kbd {
		font: inherit;
		font-size: 0.72rem;
		padding: 1px 6px;
		border-radius: 6px;
		border: 1px solid var(--border);
	}

	/* --- Notices: a toast at the top, over the page (never in its flow) --- */
	.banner {
		position: fixed;
		top: calc(10px + env(safe-area-inset-top));
		left: 50%;
		transform: translateX(-50%);
		z-index: 40;
		box-sizing: border-box;
		width: max-content;
		max-width: min(560px, calc(100vw - 32px));
		padding: 6px 6px 6px 16px;
		border-radius: 18px;
		font-size: 0.9rem;
		display: flex;
		align-items: center;
		gap: 8px;
		box-shadow: var(--glass-shadow);
	}
	/* Denser than other glass: it sits over text, or a busy map. */
	.banner.glass {
		background-color: color-mix(in srgb, var(--surface) 92%, transparent);
	}
	/* Desktop: centred in the space beside the rail. */
	.withrail .banner {
		top: 14px;
		left: calc(272px + (100vw - 272px) / 2);
		max-width: min(560px, calc(100vw - 300px));
	}
	.btxt {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
		min-width: 0;
		padding: 4px 0;
	}
	.bclose {
		flex: 0 0 32px;
		height: 32px;
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 12px;
		background: transparent;
		color: inherit;
		cursor: pointer;
	}
	.bclose:hover {
		background: var(--hover);
	}
	.bclose svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
	}
	.banner.warn {
		background: var(--warn-bg);
		border: 1px solid var(--warn-border);
		color: var(--warn-ink);
	}
	.banner a {
		color: inherit;
	}
	main {
		max-width: 1280px;
		margin: 0 auto;
		padding: 12px 16px 24px;
		padding-top: calc(12px + env(safe-area-inset-top));
	}
	.withrail main {
		padding: 4px 0 24px;
	}
	footer {
		max-width: 1280px;
		margin: 0 auto;
		padding: 8px 16px 120px;
		font-size: 0.78rem;
		color: var(--text-2);
	}
	footer span {
		display: inline-block;
		padding: 8px 14px;
		border-radius: 16px;
	}
	.withrail footer {
		padding: 8px 0 28px;
	}
	footer a {
		color: inherit;
	}

	/* --- Phone and tablet tab bar --- */
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
		transition:
			max-width var(--spring),
			padding var(--spring);
	}
	.tabbar.compact {
		max-width: 220px;
	}
	.tabbar a {
		display: grid;
		justify-items: center;
		align-content: center;
		gap: 2px;
		min-height: 46px;
		border-radius: 999px;
		color: var(--text-2);
		text-decoration: none;
		font-size: 0.7rem;
		font-weight: 500;
		transition: background-color var(--ease);
	}
	.tabbar a span {
		max-height: 16px;
		overflow: hidden;
		transition:
			max-height var(--spring),
			opacity var(--ease);
	}
	.tabbar.compact a span {
		max-height: 0;
		opacity: 0;
	}
	.tabbar svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 1.9;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.tabbar a[aria-current='page'] {
		color: var(--text);
		background: var(--sel);
		box-shadow: var(--sel-shadow);
	}
</style>
