<!--
  Every location on a map. Each marker shows the next-5-day snow on the
  Calendar's colour ramp, with a ring in the avalanche danger colour when the
  center's rating is current. Tap a marker for the numbers and a link.
  With `radar`, precipitation plays over the map on one timeline: the last two hours
  of observed radar, then the next ~48 hours of forecast, with rain, mix and snow in
  their own colours. See ../radar.ts for the sources and how they're blended.
  On phones the map fills the screen and the controls float over it.
-->
<script lang="ts">
	import 'leaflet/dist/leaflet.css';
	import type { Map as LeafletMap, GridLayer, WMSOptions } from 'leaflet';
	import type { OverviewRow } from '../types.gen';
	import { bucket } from '../calendar';
	import { dangerWord } from '../conditions';
	import { snowNum, type UnitSystem } from '../units';
	import { prefs } from '../prefs.svelte';
	import {
		frameLabel,
		GEOMET,
		hrrrSlot,
		loadTimeline,
		MODEL_LAYERS,
		RADAR_MAX_NATIVE_ZOOM,
		radarUrl,
		RAMPS,
		rampTop,
		resetSouthCache,
		sldBody,
		UNTYPED,
		untypedTop,
		wpcFor,
		type Frame,
		type Timeline,
		type WmsLayer
	} from '../radar';
	import { radarLayer, southLayer } from '../southLayer';

	interface Props {
		rows: OverviewRow[];
		units: UnitSystem;
		href: (id: string) => string;
		/** Show the precipitation layers and their controls, full screen on phones. */
		radar?: boolean;
	}

	let { rows, units, href, radar = false }: Props = $props();
	let el = $state<HTMLDivElement>();
	let wrap = $state<HTMLDivElement>();
	let map: LeafletMap | null = null;
	let L: typeof import('leaflet') | null = null;
	let markers: import('leaflet').LayerGroup | null = null;
	let ready = $state(false);
	let infoOpen = $state(false);

	// ---- Base map ------------------------------------------------------------
	// Esri's World Topo: natural colours, gentle relief, clear labels. Dimmed a little
	// in the dark theme so it doesn't glare.
	let systemDark = $state(false);
	const dark = $derived(prefs.theme === 'dark' || (prefs.theme === 'auto' && systemDark));

	$effect(() => {
		const mq = matchMedia('(prefers-color-scheme: dark)');
		systemDark = mq.matches;
		const on = (e: MediaQueryListEvent) => (systemDark = e.matches);
		mq.addEventListener('change', on);
		return () => mq.removeEventListener('change', on);
	});

	// Phones: fill the screen from the map's top down, behind the floating tab bar.
	let fillTop = $state(0);
	$effect(() => {
		if (!radar || !wrap) return;
		const measure = () => (fillTop = wrap!.getBoundingClientRect().top + window.scrollY);
		measure();
		window.addEventListener('resize', measure);
		return () => window.removeEventListener('resize', measure);
	});

	// ---- Precipitation timeline ------------------------------------------------
	const on = $derived(radar && prefs.mapPrecip === 'on');
	let timeline = $state<Timeline>({ frames: [], now: -1 });
	let loadError = $state(false);
	let frame = $state(0);
	let playing = $state(true);
	let now = $state(Date.now());
	/** The frame on screen, which lags `frame` while the next one loads. */
	let shown = $state<string | null>(null);
	/** Frames whose images are in for the current view (fetched, so cached). */
	let warm = $state<Set<string>>(new Set());
	/** The current frame's US forecast fell back to 6-hour totals (no type). */
	let untypedShown = $state(false);

	const frames = $derived(timeline.frames);
	const count = $derived(frames.length);
	const current = $derived<Frame | undefined>(frames[Math.min(frame, count - 1)]);
	const label = $derived(current ? frameLabel(current, now) : null);
	const waiting = $derived(!!current && shown !== keyFor(current));
	const pct = (i: number) => (count > 1 ? (i / (count - 1)) * 100 : 0);
	// Under the slider: "Now" where the radar ends, then each new day of the forecast.
	const ticks = $derived.by(() => {
		const out: { at: number; name: string; now?: boolean }[] = [];
		if (timeline.now >= 0 && timeline.now < count - 1)
			out.push({ at: pct(timeline.now), name: 'Now', now: true });
		frames.forEach((f, i) => {
			if (f.past || i === 0) return;
			const start = new Date((f.t - 3600) * 1000);
			// Skip a day name that would crowd "Now".
			if (start.getHours() === 0 && !(out[0]?.now && pct(i) - out[0].at < 10))
				out.push({ at: pct(i), name: start.toLocaleDateString('en-US', { weekday: 'short' }) });
		});
		return out;
	});
	// The slider track: loaded frames shaded, like a video's buffered range.
	const buffered = $derived.by(() => {
		if (count < 2) return 'none';
		const w = 100 / (count - 1);
		const stops: string[] = [];
		frames.forEach((f, i) => {
			const c = warm.has(keyFor(f)) ? 'var(--buffered)' : 'transparent';
			const a = Math.max(0, (i - 0.5) * w);
			const b = Math.min(100, (i + 0.5) * w);
			stops.push(`${c} ${a}%`, `${c} ${b}%`);
		});
		return `linear-gradient(90deg, ${stops.join(', ')})`;
	});

	const OPACITY = 0.8;
	const ECCC =
		'<a href="https://eccc-msc.github.io/open-data/">Environment and Climate Change Canada</a>';
	interface Built {
		layers: GridLayer[];
		loaded: Set<GridLayer>;
		done: Promise<void>;
		untyped: Promise<boolean>;
	}
	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- Leaflet bookkeeping, not UI state
	const built = new Map<string, Built>();
	function keyFor(f: Frame) {
		return `${f.past ? 'p' : 'f'}${f.t}`;
	}

	function wms(w: WmsLayer, time: number, attribution: string): GridLayer {
		return L!.tileLayer.wms(GEOMET, {
			layers: w.layer,
			styles: '',
			format: 'image/png',
			transparent: true,
			version: '1.3.0',
			// Big images: GeoMet rate-limits, so ask for few of them.
			tileSize: 1024,
			pane: 'precip',
			opacity: 0,
			maxZoom: 15,
			maxNativeZoom: 10,
			attribution,
			// Extra WMS parameters.
			time: new Date(time * 1000).toISOString().replace('.000Z', 'Z'),
			sld_body: sldBody(w.layer, w.ramp.steps)
		} as WMSOptions);
	}

	/** The layers for frame `f`, created and added (hidden) on first use. */
	function ensure(f: Frame): Built | null {
		if (!map || !L || !on) return null;
		const key = keyFor(f);
		const have = built.get(key);
		if (have) return have;
		let layers: GridLayer[];
		let untyped = Promise.resolve(false);
		if (f.past) {
			const url = radarUrl(f.t);
			layers = url
				? [
						radarLayer(L, url, {
							pane: 'precip',
							opacity: 0,
							maxNativeZoom: RADAR_MAX_NATIVE_ZOOM,
							maxZoom: 15,
							attribution: 'Radar © <a href="https://www.rainviewer.com">RainViewer</a>'
						})
					]
				: [];
		} else {
			const hrrr = hrrrSlot(f.t);
			untyped = hrrr.then((m) => m === null);
			layers = [
				// Under the Canadian model; clipped to outside its domain anyway.
				southLayer(
					L,
					{ hrrr, wpc: () => wpcFor(f.t) },
					{
						pane: 'precip',
						opacity: 0,
						maxZoom: 15,
						attribution:
							'US forecast: NOAA HRRR via <a href="https://mesonet.agron.iastate.edu">IEM</a>, NWS WPC'
					}
				),
				...MODEL_LAYERS.map((w) => wms(w, f.t, `Forecast © ${ECCC}`))
			];
		}
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- replaced wholesale or local bookkeeping
		const loaded = new Set<GridLayer>();
		let resolve!: () => void;
		const done = new Promise<void>((r) => (resolve = r));
		const check = () => loaded.size === layers.length && resolve();
		for (const l of layers) {
			l.on('loading', () => loaded.delete(l));
			l.on('load', () => {
				loaded.add(l);
				check();
			});
			l.on('tileerror', retryTile);
			l.addTo(map);
		}
		check();
		const b: Built = { layers, loaded, done, untyped };
		built.set(key, b);
		done.then(() => {
			// eslint-disable-next-line svelte/prefer-svelte-reactivity -- replaced wholesale or local bookkeeping
			if (built.get(key) === b) warm = new Set(warm).add(key);
		});
		return b;
	}
	/** One more try for a tile that failed (GeoMet answers 429 when busy). */
	function retryTile(e: import('leaflet').TileErrorEvent) {
		const img = e.tile as HTMLImageElement;
		if (!img.src || img.dataset.retried) return;
		img.dataset.retried = '1';
		const src = img.src;
		const sep = src.includes('?') ? '&' : '?';
		setTimeout(() => (img.src = `${src}${sep}retry=1`), 1500 + Math.random() * 1500);
	}

	function drop(key: string) {
		const b = built.get(key);
		if (!b) return;
		for (const l of b.layers) l.remove();
		built.delete(key);
	}
	function clearFrames() {
		for (const k of [...built.keys()]) drop(k);
		shown = null;
	}

	/** Frames kept on the map: the one showing, the one wanted, and the next two. */
	function keepKeys(): Set<string> {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- replaced wholesale or local bookkeeping
		const keep = new Set<string>();
		if (shown) keep.add(shown);
		for (const d of [0, 1, 2]) {
			const f = frames[(frame + d) % count];
			if (f) keep.add(keyFor(f));
		}
		return keep;
	}

	function setVisible(key: string) {
		for (const [k, b] of built) for (const l of b.layers) l.setOpacity(k === key ? OPACITY : 0);
		shown = key;
		const b = built.get(key);
		b?.untyped.then((u) => shown === key && (untypedShown = u));
		if (key.startsWith('p')) untypedShown = false;
	}

	/**
	 * Show the wanted frame. The old one stays up until the new one's images are in
	 * (or a second and a half passes), so scrubbing never flashes an empty map.
	 */
	let swapToken = 0;
	function show() {
		if (!map) return;
		if (!on || !current) return clearFrames();
		const key = keyFor(current);
		const b = ensure(current);
		for (const d of [1, 2]) {
			const f = frames[(frame + d) % count];
			if (f) ensure(f);
		}
		const keep = keepKeys();
		for (const k of [...built.keys()]) if (!keep.has(k) && !warming.has(k)) drop(k);
		if (!b) return;
		const token = ++swapToken;
		if (b.loaded.size === b.layers.length || !shown) setVisible(key);
		else
			Promise.race([b.done, new Promise((r) => setTimeout(r, 1500))]).then(() => {
				if (token === swapToken) {
					setVisible(key);
					for (const k of [...built.keys()]) if (!keepKeys().has(k) && !warming.has(k)) drop(k);
				}
			});
	}

	// ---- Background loading ----------------------------------------------------
	// Walk the whole timeline from the current frame on, two frames at a time: load
	// each one's images (the browser caches them), then let it go unless it's near
	// the current frame. Scrubbing to a loaded frame is then quick. Starts over when
	// the view moves, since the images differ.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- bookkeeping, not UI state
	const warming = new Set<string>();
	let warmRun = 0;
	function warmAll() {
		const run = ++warmRun;
		warm = new Set();
		if (!on || !count) return;
		const order = frames.map((_, d) => frames[(frame + d) % count]);
		let next = 0;
		const worker = async () => {
			while (run === warmRun && next < order.length) {
				const f = order[next++];
				const key = keyFor(f);
				const b = ensure(f);
				if (!b) return;
				warming.add(key);
				await Promise.race([b.done, new Promise((r) => setTimeout(r, 12000))]);
				warming.delete(key);
				if (!keepKeys().has(key)) drop(key);
			}
		};
		worker();
		worker();
	}

	async function refresh() {
		try {
			const before = current?.t;
			const atNow = frame === timeline.now;
			resetSouthCache();
			const tl = await loadTimeline();
			timeline = tl;
			loadError = false;
			// Keep the viewer's place if that time still exists; otherwise go to "now".
			const same = tl.frames.findIndex((f) => f.t === before);
			frame = atNow || same < 0 ? Math.max(0, tl.now) : same;
			clearFrames();
			show();
			warmAll();
		} catch {
			loadError = true;
		}
	}

	$effect(() => {
		void frame;
		void on;
		void count;
		if (!ready) return;
		// Scrubbing: a short pause so dragging past frames doesn't ask for each of them.
		if (!playing) {
			const id = setTimeout(show, 60);
			return () => clearTimeout(id);
		}
		show();
	});
	$effect(() => {
		void on;
		if (!ready) return;
		if (on) warmAll();
		else {
			warmRun++;
			clearFrames();
		}
	});

	// Play: step when the next frame is in (or after a short wait), quicker through
	// the radar, and hold a moment on "now" and on the last frame.
	$effect(() => {
		if (!ready || !playing || !on || count < 2) return;
		let hold = 0;
		let waits = 0;
		let id: ReturnType<typeof setTimeout>;
		const tick = () => {
			const past = frames[frame]?.past;
			id = setTimeout(tick, past ? 450 : 750);
			if (hold > 0) return void hold--;
			if (waiting && waits++ < 6) return;
			const next = (frame + 1) % count;
			const b = ensure(frames[next]);
			if (b && b.loaded.size < b.layers.length && waits++ < 6) return;
			waits = 0;
			frame = next;
			if (next === count - 1) hold = 3;
			else if (next === timeline.now) hold = 2;
		};
		id = setTimeout(tick, 600);
		return () => clearTimeout(id);
	});

	$effect(() => {
		if (!radar) return;
		const ids = [
			setInterval(refresh, 10 * 60 * 1000),
			setInterval(() => (now = Date.now()), 60 * 1000)
		];
		return () => ids.forEach(clearInterval);
	});

	const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

	$effect(() => {
		if (!el) return;
		let cancelled = false;
		import('leaflet').then((mod) => {
			if (cancelled || !el) return;
			L = mod.default ?? mod;
			map = L.map(el, {
				zoomControl: true,
				scrollWheelZoom: false,
				attributionControl: false
			});
			// Credits in the top-right, one line until tapped.
			L.control.attribution({ position: 'topright', prefix: false }).addTo(map);
			L.tileLayer(
				'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
				{
					maxZoom: 15,
					className: 'basemap',
					attribution:
						'Map © <a href="https://www.esri.com">Esri</a>, HERE, Garmin, USGS, NGA, EPA, USDA, NPS, © OpenStreetMap'
				}
			).addTo(map);
			// Precipitation between the terrain and the markers.
			map.createPane('precip').style.zIndex = '350';
			markers = L.layerGroup().addTo(map);
			// A new view needs new images: load the timeline again for it.
			let moveId: ReturnType<typeof setTimeout>;
			map.on('moveend', () => {
				clearTimeout(moveId);
				moveId = setTimeout(() => ready && on && warmAll(), 500);
			});
			if (radar) refresh();
			ready = true;
			draw();
		});
		return () => {
			cancelled = true;
			ready = false;
			warmRun++;
			built.clear();
			map?.remove();
			map = null;
		};
	});

	// Tap the credits to read them in full.
	$effect(() => {
		if (!ready || !el) return;
		const credits = el.querySelector('.leaflet-control-attribution');
		const toggle = (e: Event) => {
			if ((e.target as HTMLElement).tagName === 'A') return;
			credits?.classList.toggle('open');
		};
		credits?.addEventListener('click', toggle);
		return () => credits?.removeEventListener('click', toggle);
	});

	$effect(() => {
		void rows;
		void units;
		draw();
	});

	function draw() {
		if (!map || !L || !markers) return;
		markers.clearLayers();
		const placed = rows.filter((r) => r.lat !== null && r.lat !== undefined && r.lon != null);
		for (const r of placed) {
			const b = bucket(r.next5_cm);
			const danger = r.danger?.status === 'current' && r.danger.level ? r.danger.level : 0;
			const label = snowNum(r.next5_cm, units);
			const icon = L.divIcon({
				className: 'snowpin',
				html: `<span class="dot b${b}${danger ? ` ring d${danger}` : ''}">${esc(label)}</span>`,
				iconSize: [34, 34],
				iconAnchor: [17, 17]
			});
			const unit = units === 'imperial' ? 'in' : 'cm';
			const dangerLine = danger ? `<div>Avalanche ${danger} · ${dangerWord(danger)}</div>` : '';
			L.marker([r.lat!, r.lon!], { icon, title: r.name, alt: r.name })
				.bindPopup(
					`<strong>${esc(r.name)}</strong><div>${esc(label)} ${unit} in the next 5 days</div>` +
						`${dangerLine}<a href="${esc(href(r.id))}">Open forecast →</a>`
				)
				.addTo(markers);
		}
		if (placed.length) {
			const bounds = L.latLngBounds(placed.map((r) => [r.lat!, r.lon!] as [number, number]));
			map.fitBounds(bounds.pad(0.25), { maxZoom: 9 });
		}
	}

	const unit = $derived(units === 'imperial' ? 'in' : 'cm');
	const legendRamps = [RAMPS.snow, RAMPS.mix, RAMPS.rain];
	const source = $derived(
		!current
			? ''
			: current.past
				? 'Observed by radar (RainViewer).'
				: untypedShown
					? 'Forecast: Canadian HRDPS model; rest of the US, NWS 6-hour totals (no type).'
					: 'Forecast: Canadian HRDPS model; rest of the US, NOAA HRRR.'
	);
</script>

<div class="wrap" class:fill={radar} class:dark bind:this={wrap} style:--fill-top="{fillTop}px">
	<div class="map" bind:this={el} role="region" aria-label="Map of locations"></div>

	{#if radar}
		<div class="tools">
			<button
				class="tool"
				class:active={on}
				aria-pressed={on}
				onclick={() => prefs.setMapPrecip(!on)}
				title="Show or hide precipitation"
				aria-label="Precipitation"
			>
				<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
					><path
						d="M7 15a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 17 8a3.5 3.5 0 0 1 .5 7M8 18l-1 2M12 18l-1 2M16 18l-1 2"
					/></svg
				>
			</button>
			<button
				class="tool"
				class:active={infoOpen}
				aria-expanded={infoOpen}
				onclick={() => (infoOpen = !infoOpen)}
				aria-label="About this map"
			>
				<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
					><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></svg
				>
			</button>
		</div>

		{#if infoOpen}
			<div class="info" role="dialog" aria-label="About this map">
				<p class="item">
					<span class="pin" aria-hidden="true">1.2</span> Next 5 days of snow ({unit}). Tap one for
					details.
				</p>
				<p class="item">
					<span class="pin ring" aria-hidden="true"></span> Ring: avalanche danger, when rated.
				</p>
				{#if on}
					<p>{source}</p>
					<p>
						Darkest shades: snow {rampTop(RAMPS.snow, units)}, rain {rampTop(RAMPS.rain, units)}.
					</p>
					<p class="faint">
						Snow per hour assumes about 10 parts snow to 1 part water. Forecasts beyond a day are
						rougher.
					</p>
				{/if}
				<button class="close" onclick={() => (infoOpen = false)}>Close</button>
			</div>
		{/if}

		{#if on}
			<section class="controls glass" aria-label="Precipitation timeline">
				{#if count && label && current}
					<div class="player">
						<button
							class="play"
							onclick={() => (playing = !playing)}
							aria-label={playing ? 'Pause' : 'Play'}
						>
							<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
								{#if playing}<path d="M8 5v14M16 5v14" />{:else}<path d="M7 5l12 7-12 7z" />{/if}
							</svg>
						</button>
						<div class="track">
							<input
								type="range"
								min="0"
								max={Math.max(0, count - 1)}
								bind:value={frame}
								oninput={() => (playing = false)}
								aria-label="Time"
								aria-valuetext={`${label.when}, ${label.rel}`}
								style:--buffer={buffered}
							/>
							<div class="ticks" aria-hidden="true">
								{#each ticks as d (d.at)}
									<span class:now={d.now} style:left="{d.at}%">{d.name}</span>
								{/each}
							</div>
						</div>
						<div class="time" aria-live="off">
							<strong class="num">{label.when}</strong>
							<span class:fc={!current.past}
								>{label.rel}{#if waiting}<i class="spin" aria-label="Loading"></i>{/if}</span
							>
						</div>
					</div>
				{:else if loadError}
					<p class="note">Precipitation is unavailable right now.</p>
				{:else}
					<p class="note">Loading…</p>
				{/if}
				<div class="key">
					{#each legendRamps as r (r.kind)}
						<span class="kind">
							<span class="name">{r.label}</span>
							<span class="ramp" aria-hidden="true">
								{#each r.steps as s (s.from)}<i style:background={s.color}></i>{/each}
							</span>
							<span class="top">{rampTop(r, units)}</span>
						</span>
					{/each}
					{#if untypedShown}
						<span class="kind">
							<span class="name">No type</span>
							<span class="ramp" aria-hidden="true">
								{#each UNTYPED as s (s.from)}<i style:background={s.color}></i>{/each}
							</span>
							<span class="top">{untypedTop(units)}</span>
						</span>
					{/if}
				</div>
			</section>
		{/if}
	{/if}
</div>
{#if !radar}
	<p class="faint small legend">
		<span class="item"
			><span class="pin" aria-hidden="true">1.2</span> Next 5 days of snow ({unit})</span
		>
		<span class="item"
			><span class="pin ring" aria-hidden="true"></span> Ring: avalanche danger, when rated</span
		>
	</p>
{/if}

<style>
	.wrap {
		position: relative;
		/* Keep Leaflet's layers inside, under the floating tab bar. */
		isolation: isolate;
		z-index: 0;
		--buffered: color-mix(in srgb, var(--accent) 28%, transparent);
	}
	.map {
		height: min(70vh, 560px);
		border-radius: var(--radius);
		overflow: hidden;
		border: 1px solid var(--border);
	}
	/* The full map: a tall card on desktop. */
	.fill .map {
		height: clamp(420px, calc(100dvh - 190px), 900px);
	}
	/* Phones and tablets: edge to edge, from the header to the bottom of the screen,
	   with the tab bar floating over it. */
	@media (max-width: 1099px) {
		.wrap.fill {
			margin: -16px -16px 0;
		}
		.fill .map {
			height: calc(100dvh - var(--fill-top));
			min-height: 360px;
			border-radius: 0;
			border: 0;
		}
	}
	/* Esri's topo tiles have a lighter last row and column, which draw a faint grid.
	   Stretch each tile by a pixel and clip that edge off. */
	.map :global(.basemap img.leaflet-tile) {
		width: 257px !important;
		height: 257px !important;
		clip-path: inset(0 1px 1px 0);
	}
	.dark .map :global(.basemap) {
		filter: brightness(0.68) saturate(0.85) contrast(0.95);
	}

	/* Credits: one line, tap for all. */
	.map :global(.leaflet-control-attribution) {
		max-width: min(70vw, 520px);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		font-size: 0.65rem;
		cursor: pointer;
		border-bottom-left-radius: 6px;
	}
	.map :global(.leaflet-control-attribution.open) {
		white-space: normal;
	}

	.tools {
		position: absolute;
		top: 86px;
		left: 10px;
		z-index: 1000;
		display: grid;
		gap: 6px;
	}
	.tool {
		width: 34px;
		height: 34px;
		display: grid;
		place-items: center;
		border-radius: 4px;
		border: 2px solid rgb(0 0 0 / 0.2);
		background-clip: padding-box;
		background: #fff;
		color: #333;
		cursor: pointer;
	}
	.tool.active {
		background: var(--accent);
		color: #fff;
	}
	.tool svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	.info {
		position: absolute;
		top: 86px;
		left: 54px;
		right: 10px;
		max-width: 360px;
		z-index: 1001;
		padding: 12px 14px;
		border-radius: 14px;
		background: var(--surface);
		border: 1px solid var(--border);
		box-shadow: var(--glass-shadow);
		font-size: 0.8rem;
		color: var(--text);
		display: grid;
		gap: 6px;
	}
	.info p {
		margin: 0;
	}
	.info .close {
		justify-self: end;
		border: 0;
		background: transparent;
		color: var(--accent);
		font-weight: 600;
		cursor: pointer;
		padding: 2px 4px;
	}

	.controls {
		position: absolute;
		left: 10px;
		right: 10px;
		bottom: 10px;
		z-index: 1000;
		max-width: 640px;
		margin: 0 auto;
		display: grid;
		gap: 6px;
		padding: 8px 12px 8px 8px;
		border-radius: 18px;
		font-size: 0.85rem;
	}
	/* Clear the floating tab bar on phones. */
	@media (max-width: 1099px) {
		.controls {
			bottom: calc(84px + env(safe-area-inset-bottom));
		}
	}
	.player {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.play {
		width: 38px;
		height: 38px;
		flex-shrink: 0;
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 999px;
		background: var(--accent);
		color: var(--surface);
		cursor: pointer;
	}
	.play svg {
		fill: currentColor;
		stroke: currentColor;
		stroke-width: 2.4;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.track {
		flex: 1;
		min-width: 0;
		position: relative;
	}
	.track input {
		width: 100%;
		margin: 0;
		accent-color: var(--accent);
		background: var(--buffer, none);
		border-radius: 999px;
	}
	.ticks {
		position: relative;
		height: 13px;
		margin: 0 8px;
	}
	.ticks span {
		position: absolute;
		top: 0;
		transform: translateX(-50%);
		font-size: 0.68rem;
		color: var(--text-2);
		border-left: 1px solid var(--border);
		padding-left: 3px;
		line-height: 1;
		white-space: nowrap;
	}
	.ticks span.now {
		color: var(--accent-ink);
		font-weight: 600;
		border-left-color: var(--accent);
	}
	.time {
		display: grid;
		text-align: right;
		flex-shrink: 0;
		min-width: 88px;
		line-height: 1.25;
	}
	.time strong {
		color: var(--text);
		white-space: nowrap;
	}
	.time span {
		color: var(--text-2);
		font-size: 0.72rem;
		white-space: nowrap;
	}
	.time span.fc {
		color: var(--accent-ink);
	}
	.spin {
		display: inline-block;
		width: 9px;
		height: 9px;
		margin-left: 5px;
		border: 2px solid currentColor;
		border-right-color: transparent;
		border-radius: 50%;
		vertical-align: -1px;
		animation: spin 0.8s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.note {
		margin: 4px 6px;
		color: var(--text-2);
	}
	.key {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 12px;
		font-size: 0.7rem;
		color: var(--text-2);
		padding-left: 4px;
	}
	.kind {
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}
	.kind .name {
		font-weight: 600;
		color: var(--text);
	}
	.ramp {
		display: inline-flex;
		height: 9px;
		border-radius: 3px;
		overflow: hidden;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.08);
	}
	.ramp i {
		width: 9px;
	}
	/* Phones: keep the key to one line; the amounts are in the info panel. */
	@media (max-width: 480px) {
		.key .top {
			display: none;
		}
	}

	.legend {
		margin: 8px 0 0;
		font-size: 0.8rem;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 6px;
	}
	.item {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.legend .item {
		margin-right: 10px;
	}
	.pin {
		display: inline-grid;
		place-items: center;
		flex-shrink: 0;
		min-width: 20px;
		height: 20px;
		padding: 0 3px;
		border-radius: 999px;
		background: var(--c2);
		color: var(--c-ink-light);
		border: 2px solid #fff;
		box-shadow: 0 1px 2px rgb(0 0 0 / 0.3);
		font: 600 10px/1 var(--font-num, sans-serif);
	}
	.pin.ring {
		background: var(--c0);
		border: 3px solid var(--d3);
	}
	:global(.snowpin .dot) {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 50%;
		font: 600 12px/1 var(--font-num, sans-serif);
		box-shadow: 0 1px 3px rgb(0 0 0 / 0.35);
		border: 2px solid #fff;
	}
	:global(.snowpin .dot.ring) {
		border-width: 4px;
	}
	:global(.snowpin .b0) {
		background: var(--c0);
		color: var(--text);
	}
	:global(.snowpin .b1) {
		background: var(--c1);
		color: var(--c-ink-light);
	}
	:global(.snowpin .b2) {
		background: var(--c2);
		color: var(--c-ink-light);
	}
	:global(.snowpin .b3) {
		background: var(--c3);
		color: var(--c-ink-dark);
	}
	:global(.snowpin .b4) {
		background: var(--c4);
		color: var(--c-ink-dark);
	}
	:global(.snowpin .b5) {
		background: var(--c5);
		color: var(--c-ink-dark);
	}
	:global(.snowpin .d1) {
		border-color: var(--d1);
	}
	:global(.snowpin .d2) {
		border-color: var(--d2);
	}
	:global(.snowpin .d3) {
		border-color: var(--d3);
	}
	:global(.snowpin .d4) {
		border-color: var(--d4);
	}
	:global(.snowpin .d5) {
		border-color: var(--d5);
	}
</style>
