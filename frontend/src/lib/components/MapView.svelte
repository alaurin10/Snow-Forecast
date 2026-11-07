<!--
  Every location on a map. Each marker shows the next-5-day snow on the
  Calendar's colour ramp, with a ring in the avalanche danger colour when the
  center's rating is current. Tap a marker for the numbers and a link.
  With `radar`, a precipitation layer plays over the map: the last two hours of
  observed radar, or the next ~48 hours of model forecast with rain, freezing rain
  and snow in their own colours.
-->
<script lang="ts">
	import 'leaflet/dist/leaflet.css';
	import type { Map as LeafletMap, TileLayer } from 'leaflet';
	import type { OverviewRow } from '../types.gen';
	import { bucket } from '../calendar';
	import { dangerWord } from '../conditions';
	import { snowNum, type UnitSystem } from '../units';
	import { prefs, type MapLayer } from '../prefs.svelte';
	import {
		FORECAST_WMS,
		forecastLabel,
		frameLabel,
		loadForecastTimes,
		loadRadar,
		RADAR_MAX_NATIVE_ZOOM,
		RAMPS,
		rampTop,
		sldBody,
		type RadarFrame
	} from '../radar';

	interface Props {
		rows: OverviewRow[];
		units: UnitSystem;
		href: (id: string) => string;
		/** Show the precipitation layers and their controls. */
		radar?: boolean;
	}

	let { rows, units, href, radar = false }: Props = $props();
	let el = $state<HTMLDivElement>();
	let map: LeafletMap | null = null;
	let L: typeof import('leaflet') | null = null;
	let markers: import('leaflet').LayerGroup | null = null;
	let ready = $state(false);

	// ---- Base map ------------------------------------------------------------
	// The topo map, either in full colour or muted to greys (dark greys in the dark
	// theme) so the precipitation colours stand out against it.
	let systemDark = $state(false);
	const dark = $derived(prefs.theme === 'dark' || (prefs.theme === 'auto' && systemDark));
	const muted = $derived(radar && prefs.basemap === 'muted');

	$effect(() => {
		const mq = matchMedia('(prefers-color-scheme: dark)');
		systemDark = mq.matches;
		const on = (e: MediaQueryListEvent) => (systemDark = e.matches);
		mq.addEventListener('change', on);
		return () => mq.removeEventListener('change', on);
	});

	// ---- Precipitation frames ------------------------------------------------
	const mode = $derived<MapLayer>(radar ? prefs.mapLayer : 'off');
	let radarFrames = $state<RadarFrame[]>([]);
	let fcTimes = $state<number[]>([]);
	let radarError = $state(false);
	let fcError = $state(false);
	let frame = $state(0);
	let playing = $state(true);
	let now = $state(Date.now());

	const times = $derived(
		mode === 'radar' ? radarFrames.map((f) => f.time) : mode === 'forecast' ? fcTimes : []
	);
	const count = $derived(times.length);
	const label = $derived.by(() => {
		const t = times[Math.min(frame, count - 1)];
		if (t === undefined) return null;
		return mode === 'radar' ? frameLabel(t, now) : forecastLabel(t, now);
	});
	// Day names under the forecast slider, at each local midnight.
	const dayTicks = $derived.by(() => {
		if (mode !== 'forecast' || count < 2) return [];
		const out: { at: number; name: string }[] = [];
		times.forEach((t, i) => {
			const start = new Date((t - 3600) * 1000);
			if (i > 0 && start.getHours() === 0)
				out.push({
					at: (i / (count - 1)) * 100,
					name: start.toLocaleDateString('en-US', { weekday: 'short' })
				});
		});
		return out;
	});

	const OPACITY = { radar: 0.75, forecast: 0.8 };
	// Built frames, by key. Each holds one tile layer (radar) or one per precip type
	// (forecast), kept on the map at opacity 0 until shown so the loop doesn't flash.
	interface Built {
		layers: TileLayer[];
		loaded: Set<TileLayer>;
	}
	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- Leaflet bookkeeping, not UI state
	const built = new Map<string, Built>();
	const keyFor = (i: number) => `${mode}:${times[i]}`;

	function ensure(i: number): Built | null {
		if (!map || !L || mode === 'off' || i < 0 || i >= count) return null;
		const key = keyFor(i);
		const have = built.get(key);
		if (have) return have;
		const t = times[i];
		let layers: TileLayer[];
		if (mode === 'radar') {
			const f = radarFrames[i];
			layers = [
				L.tileLayer(f.url, {
					pane: 'precip',
					opacity: 0,
					maxNativeZoom: RADAR_MAX_NATIVE_ZOOM,
					maxZoom: 15,
					attribution: 'Radar © <a href="https://www.rainviewer.com">RainViewer</a>'
				})
			];
		} else {
			const time = new Date(t * 1000).toISOString().replace('.000Z', 'Z');
			layers = RAMPS.map((r) =>
				L!.tileLayer.wms(FORECAST_WMS, {
					layers: r.layer,
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
					attribution:
						'Forecast © <a href="https://eccc-msc.github.io/open-data/">Environment and Climate Change Canada</a>',
					// Extra WMS parameters.
					time,
					sld_body: sldBody(r)
				} as import('leaflet').WMSOptions)
			);
		}
		const b: Built = { layers, loaded: new Set() };
		for (const l of layers) {
			l.on('loading', () => b.loaded.delete(l));
			l.on('load', () => b.loaded.add(l));
			l.on('tileerror', retryTile);
			l.addTo(map);
		}
		built.set(key, b);
		return b;
	}
	/** One more try for a tile that failed (GeoMet answers 429 when busy). */
	function retryTile(e: import('leaflet').TileErrorEvent) {
		const img = e.tile as HTMLImageElement;
		if (img.dataset.retried) return;
		img.dataset.retried = '1';
		const src = img.src;
		const sep = src.includes('?') ? '&' : '?';
		setTimeout(() => (img.src = `${src}${sep}retry=1`), 1500 + Math.random() * 1500);
	}
	const isLoaded = (b: Built | null) => !b || b.loaded.size === b.layers.length;

	function clearFrames() {
		for (const b of built.values()) for (const l of b.layers) l.remove();
		built.clear();
	}

	/** Show the current frame, preload the next ones, and drop those far behind. */
	function show() {
		if (!map || mode === 'off' || !count) return;
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local scratch, not state
		const keep = new Set<string>();
		for (const d of mode === 'radar' ? [-1, 0, 1, 2] : [0, 1]) {
			const i = (frame + d + count) % count;
			ensure(i);
			keep.add(keyFor(i));
		}
		const current = keyFor(frame);
		for (const [k, b] of built) {
			if (!keep.has(k)) {
				for (const l of b.layers) l.remove();
				built.delete(k);
			} else {
				const op = k === current ? OPACITY[mode as 'radar' | 'forecast'] : 0;
				for (const l of b.layers) l.setOpacity(op);
			}
		}
	}

	async function refreshRadar() {
		try {
			radarFrames = await loadRadar();
			radarError = false;
		} catch {
			radarError = true;
		}
	}
	async function refreshForecast() {
		try {
			fcTimes = await loadForecastTimes();
			fcError = false;
		} catch {
			fcError = true;
		}
	}

	function choose(m: MapLayer) {
		if (m === mode) return;
		prefs.setMapLayer(m);
	}

	// A new layer: start the radar at the latest frame and the forecast at this hour.
	let lastMode: MapLayer | null = null;
	let lastCount = 0;
	$effect(() => {
		const m = mode;
		const n = count;
		if (!ready) return;
		if (m !== lastMode) {
			clearFrames();
			frame = m === 'radar' ? Math.max(0, n - 1) : 0;
			playing = true;
			lastMode = m;
		} else if (n !== lastCount) {
			frame = m === 'radar' ? Math.max(0, n - 1) : Math.min(frame, Math.max(0, n - 1));
		}
		lastCount = n;
	});
	$effect(() => {
		void frame;
		void mode;
		void count;
		if (!ready) return;
		// Scrubbing the forecast: wait until the slider settles before asking for images.
		if (mode === 'forecast' && !playing) {
			const id = setTimeout(show, 150);
			return () => clearTimeout(id);
		}
		show();
	});

	// Play: step when the next frame's images are in (or after a short wait), and
	// hold a moment on the last frame before looping.
	$effect(() => {
		if (!ready || !playing || mode === 'off' || count < 2) return;
		let hold = 0;
		let waits = 0;
		const id = setInterval(
			() => {
				if (hold > 0) return void hold--;
				const next = (frame + 1) % count;
				if (!isLoaded(ensure(next)) && waits++ < 4) return;
				waits = 0;
				frame = next;
				if (next === count - 1) hold = 3;
			},
			mode === 'radar' ? 500 : 900
		);
		return () => clearInterval(id);
	});

	$effect(() => {
		if (!radar) return;
		const ids = [
			setInterval(refreshRadar, 10 * 60 * 1000),
			setInterval(refreshForecast, 30 * 60 * 1000),
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
			map = L.map(el, { zoomControl: true, scrollWheelZoom: false });
			L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
				maxZoom: 15,
				attribution:
					'Map © <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>, SRTM | Style © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'
			}).addTo(map);
			// Precipitation between the terrain and the markers.
			map.createPane('precip').style.zIndex = '350';
			markers = L.layerGroup().addTo(map);
			if (radar) {
				refreshRadar();
				refreshForecast();
			}
			ready = true;
			draw();
		});
		return () => {
			cancelled = true;
			ready = false;
			built.clear();
			lastMode = null;
			map?.remove();
			map = null;
		};
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
	const legendRamps = [...RAMPS].reverse();
	const modes: { id: MapLayer; name: string }[] = [
		{ id: 'radar', name: 'Radar' },
		{ id: 'forecast', name: 'Forecast' },
		{ id: 'off', name: 'Off' }
	];
</script>

<div class="wrap" class:with-controls={radar}>
	<div
		class="map"
		class:tall={radar}
		class:muted
		class:dark
		bind:this={el}
		role="region"
		aria-label="Map of locations"
	></div>
	{#if radar}
		<section class="controls" aria-label="Precipitation layer">
			<div class="row">
				<div class="seg" role="group" aria-label="Precipitation">
					{#each modes as m (m.id)}
						<button aria-pressed={mode === m.id} onclick={() => choose(m.id)}>{m.name}</button>
					{/each}
				</div>
				<div class="seg" role="group" aria-label="Map colours">
					<button aria-pressed={muted} onclick={() => prefs.setBasemap('muted')}>Muted</button>
					<button aria-pressed={!muted} onclick={() => prefs.setBasemap('color')}>Colour</button>
				</div>
			</div>

			{#if mode !== 'off'}
				{#if count && label}
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
								aria-label={mode === 'radar' ? 'Radar time' : 'Forecast hour'}
								aria-valuetext={`${label.when}, ${label.rel}`}
							/>
							{#if dayTicks.length}
								<div class="ticks" aria-hidden="true">
									{#each dayTicks as d (d.at)}
										<span style:left="{d.at}%">{d.name}</span>
									{/each}
								</div>
							{/if}
						</div>
						<div class="time" aria-live="off">
							<strong class="num">{label.when}</strong>
							<span>{label.rel}</span>
						</div>
					</div>
				{:else if (mode === 'radar' && radarError) || (mode === 'forecast' && fcError)}
					<p class="note">
						{mode === 'radar' ? 'Radar' : 'The forecast layer'} is unavailable right now.
					</p>
				{:else}
					<p class="note">Loading…</p>
				{/if}

				<div class="key">
					{#if mode === 'radar'}
						<span class="kind">
							<span class="name">Snow</span>
							<span class="ramp grad snow" aria-hidden="true"></span>
						</span>
						<span class="kind">
							<span class="name">Rain</span>
							<span class="ramp grad rain" aria-hidden="true"></span>
						</span>
						<span class="faint src">Light → heavy · observed by radar, last 2 hours</span>
					{:else}
						{#each legendRamps as r (r.kind)}
							<span class="kind">
								<span class="name">{r.label}</span>
								<span class="ramp" aria-hidden="true">
									{#each r.steps as s (s.from)}<i style:background={s.color}></i>{/each}
								</span>
								<span class="faint">{rampTop(r, units)}</span>
							</span>
						{/each}
						<span class="faint src">Hourly amounts · Canadian HRDPS model, 2.5 km</span>
					{/if}
				</div>
			{/if}
		</section>
	{/if}
</div>
<p class="faint small legend">
	<span class="item"
		><span class="pin" aria-hidden="true">1.2</span> Next 5 days of snow ({unit})</span
	>
	<span class="item"
		><span class="pin ring" aria-hidden="true"></span> Ring: avalanche danger, when rated</span
	>
</p>

<style>
	.wrap {
		position: relative;
	}
	.map {
		height: min(70vh, 560px);
		border-radius: var(--radius);
		overflow: hidden;
		border: 1px solid var(--border);
	}
	.map.tall {
		height: clamp(360px, calc(100dvh - 330px), 700px);
	}
	/* Grey terrain: the radar and forecast colours read clearly on top of it. */
	.map.muted :global(.leaflet-tile-pane) {
		filter: grayscale(1) contrast(0.85) brightness(1.08);
	}
	.map.muted.dark :global(.leaflet-tile-pane) {
		filter: grayscale(1) invert(1) contrast(0.75) brightness(0.8);
	}
	.with-controls .map {
		border-bottom-left-radius: 0;
		border-bottom-right-radius: 0;
	}
	/* Phones and tablets: leave room for the header, the controls and the bottom tab
	   bar so the map and its controls fit on one screen. */
	@media (max-width: 1099px) {
		.map.tall {
			height: clamp(300px, calc(100dvh - 420px), 700px);
		}
	}

	.controls {
		display: grid;
		gap: 10px;
		padding: 10px 12px 12px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-top: 0;
		border-radius: 0 0 var(--radius) var(--radius);
		font-size: 0.85rem;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 8px;
	}
	.player {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.play {
		width: 36px;
		height: 36px;
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
	}
	.ticks {
		position: relative;
		height: 14px;
		margin: 0 8px;
	}
	.ticks span {
		position: absolute;
		top: 0;
		transform: translateX(-50%);
		font-size: 0.7rem;
		color: var(--text-3);
		border-left: 1px solid var(--border);
		padding-left: 3px;
		line-height: 1;
	}
	.time {
		display: grid;
		text-align: right;
		flex-shrink: 0;
		min-width: 92px;
		line-height: 1.25;
	}
	.time strong {
		color: var(--text);
		white-space: nowrap;
	}
	.time span {
		color: var(--text-3);
		font-size: 0.75rem;
		white-space: nowrap;
	}
	.note {
		margin: 0;
		color: var(--text-2);
	}
	.key {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 16px;
		font-size: 0.75rem;
		color: var(--text-2);
	}
	.kind {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.kind .name {
		font-weight: 600;
		color: var(--text);
	}
	.ramp {
		display: inline-flex;
		height: 10px;
		border-radius: 3px;
		overflow: hidden;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.08);
	}
	.ramp i {
		width: 12px;
	}
	/* RainViewer's "Universal Blue" scheme, sampled from its tiles. */
	.ramp.grad {
		width: 72px;
	}
	.ramp.rain {
		background: linear-gradient(90deg, #88ddee, #0099cc, #004e78, #ffee00, #ff9f00, #ff4400);
	}
	.ramp.snow {
		background: linear-gradient(90deg, #c3e3ff, #85c5ff, #5b9bff, #3b7bef);
	}
	.src {
		flex-basis: 100%;
	}
	.legend {
		margin: 8px 0 0;
		font-size: 0.8rem;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 6px;
	}
	.pin {
		display: inline-grid;
		place-items: center;
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
	.legend .item {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin-right: 10px;
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
