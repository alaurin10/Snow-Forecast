<!--
  Every location on a map. Each marker shows the next-5-day snow on the
  Calendar's colour ramp, with a ring in the avalanche danger colour when the
  center's rating is current. Tap a marker for the numbers and a link.
  With `radar`, precipitation plays over the map on one timeline: the last two hours
  of observed radar, then the next ~48 hours of forecast, with rain, mix and snow in
  their own colours. See ../radar.ts for the sources and how they're blended.
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

	// ---- Precipitation timeline ------------------------------------------------
	const on = $derived(radar && prefs.mapPrecip === 'on');
	let timeline = $state<Timeline>({ frames: [], now: -1 });
	let loadError = $state(false);
	let frame = $state(0);
	let playing = $state(true);
	let now = $state(Date.now());
	/** The current frame's US forecast fell back to 6-hour totals (no type). */
	let untypedShown = $state(false);

	const frames = $derived(timeline.frames);
	const count = $derived(frames.length);
	const current = $derived<Frame | undefined>(frames[Math.min(frame, count - 1)]);
	const label = $derived(current ? frameLabel(current, now) : null);
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
			if (start.getHours() === 0 && !(out[0]?.now && pct(i) - out[0].at < 9))
				out.push({ at: pct(i), name: start.toLocaleDateString('en-US', { weekday: 'short' }) });
		});
		return out;
	});

	const OPACITY = 0.8;
	const ECCC =
		'<a href="https://eccc-msc.github.io/open-data/">Environment and Climate Change Canada</a>';
	// Built frames, by key, each a few layers kept on the map at opacity 0 until shown
	// so the loop doesn't flash.
	interface Built {
		layers: GridLayer[];
		loaded: Set<GridLayer>;
		untyped: Promise<boolean>;
	}
	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- Leaflet bookkeeping, not UI state
	const built = new Map<string, Built>();
	const keyFor = (f: Frame) => `${f.past ? 'p' : 'f'}${f.t}`;

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

	function ensure(i: number): Built | null {
		if (!map || !L || !on || i < 0 || i >= count) return null;
		const f = frames[i];
		const have = built.get(keyFor(f));
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
							'US forecast: NOAA HRRR via <a href="https://mesonet.agron.iastate.edu">Iowa Environmental Mesonet</a>, NWS WPC'
					}
				),
				...MODEL_LAYERS.map((w) => wms(w, f.t, `Forecast © ${ECCC}`))
			];
		}
		const b: Built = { layers, loaded: new Set(), untyped };
		for (const l of layers) {
			l.on('loading', () => b.loaded.delete(l));
			l.on('load', () => b.loaded.add(l));
			l.on('tileerror', retryTile);
			l.addTo(map);
		}
		built.set(keyFor(f), b);
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
	const isLoaded = (b: Built | null) => !b || b.loaded.size === b.layers.length;

	function clearFrames() {
		for (const b of built.values()) for (const l of b.layers) l.remove();
		built.clear();
	}

	/** Show the current frame, preload the next, and drop the rest. */
	function show() {
		if (!map) return;
		if (!on || !count) return clearFrames();
		const want = [frame, (frame + 1) % count].map((i) => keyFor(frames[i]));
		for (const i of [frame, (frame + 1) % count]) ensure(i);
		const cur = keyFor(frames[frame]);
		for (const [k, b] of built) {
			if (!want.includes(k)) {
				for (const l of b.layers) l.remove();
				built.delete(k);
			} else {
				for (const l of b.layers) l.setOpacity(k === cur ? OPACITY : 0);
				if (k === cur) b.untyped.then((u) => keyFor(frames[frame]) === k && (untypedShown = u));
			}
		}
		if (frames[frame].past) untypedShown = false;
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
		} catch {
			loadError = true;
		}
	}

	$effect(() => {
		void frame;
		void on;
		void count;
		if (!ready) return;
		// Scrubbing: wait until the slider settles before asking for images.
		if (!playing) {
			const id = setTimeout(show, 150);
			return () => clearTimeout(id);
		}
		show();
	});

	// Play: step when the next frame's images are in (or after a short wait), quicker
	// through the radar, and hold a moment on "now" and on the last frame.
	$effect(() => {
		if (!ready || !playing || !on || count < 2) return;
		let hold = 0;
		let waits = 0;
		let id: ReturnType<typeof setTimeout>;
		const tick = () => {
			const past = frames[frame]?.past;
			id = setTimeout(tick, past ? 450 : 800);
			if (hold > 0) return void hold--;
			const next = (frame + 1) % count;
			if (!isLoaded(ensure(next)) && waits++ < 5) return;
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
			map = L.map(el, { zoomControl: true, scrollWheelZoom: false });
			L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
				maxZoom: 15,
				attribution:
					'Map © <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>, SRTM | Style © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'
			}).addTo(map);
			// Precipitation between the terrain and the markers.
			map.createPane('precip').style.zIndex = '350';
			markers = L.layerGroup().addTo(map);
			if (radar) refresh();
			ready = true;
			draw();
		});
		return () => {
			cancelled = true;
			ready = false;
			built.clear();
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
	const legendRamps = [RAMPS.snow, RAMPS.mix, RAMPS.rain];
	const source = $derived(
		!current
			? ''
			: current.past
				? 'Observed by radar'
				: untypedShown
					? 'Forecast: Canadian HRDPS model; rest of US, NWS 6-hour totals'
					: 'Forecast: Canadian HRDPS model; rest of US, NOAA HRRR'
	);
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
		<section class="controls" aria-label="Precipitation">
			{#if on}
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
								style:--now="{timeline.now >= 0 ? pct(timeline.now) : 0}%"
								class:has-past={timeline.now >= 0}
							/>
							<div class="ticks" aria-hidden="true">
								{#each ticks as d (d.at)}
									<span class:now={d.now} style:left="{d.at}%">{d.name}</span>
								{/each}
							</div>
						</div>
						<div class="time" aria-live="off">
							<strong class="num">{label.when}</strong>
							<span class:fc={!current.past}>{label.rel}</span>
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
							<span class="faint">{rampTop(r, units)}</span>
						</span>
					{/each}
					{#if untypedShown}
						<span class="kind">
							<span class="name">Type unknown</span>
							<span class="ramp" aria-hidden="true">
								{#each UNTYPED as s (s.from)}<i style:background={s.color}></i>{/each}
							</span>
							<span class="faint">{untypedTop(units)}</span>
						</span>
					{/if}
					<span class="faint src">{source}</span>
				</div>
			{/if}
			<div class="row">
				<button
					class="toggle"
					aria-pressed={on}
					onclick={() => prefs.setMapPrecip(!on)}
					title="Show or hide precipitation">Precipitation</button
				>
				<div class="seg" role="group" aria-label="Map colours">
					<button aria-pressed={muted} onclick={() => prefs.setBasemap('muted')}>Muted</button>
					<button aria-pressed={!muted} onclick={() => prefs.setBasemap('color')}>Colour</button>
				</div>
			</div>
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
	/* The radar part of the track, before "now", in a lighter shade. */
	.track input.has-past {
		background: linear-gradient(90deg, var(--accent-soft) var(--now), transparent var(--now));
		border-radius: 999px;
	}
	.ticks span.now {
		color: var(--accent-ink);
		font-weight: 600;
		border-left-color: var(--accent);
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
	.time span.fc {
		color: var(--accent-ink);
	}
	.toggle {
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 4px 12px;
		font-size: 0.85rem;
		cursor: pointer;
		background: var(--surface-2);
		color: var(--text-2);
	}
	.toggle[aria-pressed='true'] {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--surface);
		font-weight: 600;
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
