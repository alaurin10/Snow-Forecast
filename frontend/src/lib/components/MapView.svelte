<!--
  Every location on a map. Each marker shows the next-5-day snow on the
  Calendar's colour ramp, with a ring in the avalanche danger colour when the
  center's rating is current. Tap a marker for the numbers and a link.
  With `radar`, the map fills the window and becomes the full Map page: one weather
  layer (radar, nowcast and forecast on one timeline, see ../radar.ts, or snow totals),
  one terrain overlay (slope, aspect, elevation bands, sun and shade, or the likely wind
  effect, all computed in the browser, see ../map/terrain/), hill shading, contours, ski
  runs and peaks, chosen in the Layers sheet. Tap the map for the terrain there. It's a MapLibre map: tilt and turn it, and
  switch on 3D terrain.
-->
<script lang="ts">
	import 'maplibre-gl/dist/maplibre-gl.css';
	import maplibreWorker from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
	import type { Map as MlMap, Marker, Popup } from 'maplibre-gl';
	import type { OverviewRow } from '../types.gen';
	import { bucket } from '../calendar';
	import { dangerWord } from '../conditions';
	import { snowNum, type UnitSystem } from '../units';
	import { getMapWind } from '../api';
	import type { MapWindOut } from '../types.gen';
	import { prefs } from '../prefs.svelte';
	import { viewport } from '../viewport.svelte';
	import {
		frameLabel,
		frameSource,
		loadTimeline,
		PrecipError,
		RADAR_GAPS,
		RAMPS,
		rampTop,
		totalSources,
		type Frame,
		type Timeline
	} from '../radar';
	import { FrameStore, PrecipLayer } from '../precipOverlay';
	import { UserLocation, type LocState } from '../userLocation';
	import OfflineMaps from './OfflineMaps.svelte';
	import {
		basePaint,
		DETAIL_ZOOM,
		EXAGGERATION,
		halo,
		mapStyle,
		OTM_OPACITY,
		peakColor,
		peakLabel,
		peakText,
		PEAK_LAYERS,
		ANALYSIS_OPACITY,
		PRECIP_BEFORE,
		PRECIP_OPACITY,
		sky,
		SKI_LAYERS,
		SUN_MIN_ZOOM,
		TOTAL_OPACITY,
		WIND_MIN_ZOOM
	} from '../map/style';
	import { AnalysisLayer, AreaRunner, viewBounds, type AreaState } from '../map/layers/analysis';
	import type { AreaJob } from '../map/terrain/client';
	import type { SunFacts } from '../map/terrain/shade';
	import { sunDay, sunPosition, type Ymd } from '../map/terrain/sun';
	import { WIND_WINDOWS, windSource, type WindWindow } from '../map/windsource';
	import TerrainControls from '../map/TerrainControls.svelte';
	import {
		contourTiles,
		setContours,
		setOverlay,
		setShade,
		setTerrainUnits,
		setupTerrain
	} from '../map/layers/terrain';
	import { terrainClient } from '../map/terrain/client';
	import type { PointFacts } from '../map/terrain/messages';
	import TimelineControls from '../map/Timeline.svelte';
	import LayersSheet from '../map/LayersSheet.svelte';
	import Legend from '../map/Legend.svelte';
	import Inspector from '../map/Inspector.svelte';

	interface Props {
		rows: OverviewRow[];
		units: UnitSystem;
		href: (id: string) => string;
		/** The full map: weather, terrain, their controls, and the whole window. */
		radar?: boolean;
	}

	let { rows, units, href, radar = false }: Props = $props();
	let el = $state<HTMLDivElement>();
	let wrap = $state<HTMLDivElement>();
	let map: MlMap | null = null;
	let ml: typeof import('maplibre-gl') | null = null;
	let markers: Marker[] = [];
	let popups: Popup[] = [];
	let ready = $state(false);
	/** Which floating panel is open (one at a time). */
	let panel = $state<'none' | 'info' | 'offline' | 'layers'>('none');
	let loc: UserLocation | null = null;
	let locState = $state<LocState>('off');
	const canLocate = UserLocation.supported();
	/** No connection: the map shows only what's saved (OpenTopoMap at every zoom). */
	let offline = $state(typeof navigator !== 'undefined' && navigator.onLine === false);
	let zoom = $state(0);
	/** The terrain worker is running (slope, aspect, the inspector, gap-filled elevation). */
	let analysis = $state(false);
	let contoursReady = $state(false);

	const terrainOn = $derived(radar && prefs.mapTerrain === 'on');
	const satellite = $derived(radar && prefs.mapBase === 'satellite');
	const runsOn = $derived(radar && prefs.mapFeatures.has('runs'));
	const peaksOn = $derived(!radar || prefs.mapFeatures.has('peaks'));
	/** Contours show on satellite: the topo maps draw their own. */
	const contoursOn = $derived(radar && prefs.mapFeatures.has('contours') && satellite && !offline);
	const overlayMode = $derived(radar ? prefs.mapOverlay : 'none');
	// The precipitation pictures are ~1.4 km a pixel: they fade as the map zooms past
	// that and are gone up close, where one pixel would fill the screen.
	const totalsMode = $derived(radar && prefs.mapWeather === 'totals');
	/** Snow totals are smooth fields: they stay on further in than the hourly frames. */
	const tooClose = $derived(zoom >= (totalsMode ? 15 : 13));

	function togglePanel(p: 'info' | 'offline' | 'layers') {
		panel = panel === p ? 'none' : p;
	}

	// ---- Theme ----------------------------------------------------------------
	let systemDark = $state(false);
	const dark = $derived(prefs.theme === 'dark' || (prefs.theme === 'auto' && systemDark));

	$effect(() => {
		const mq = matchMedia('(prefers-color-scheme: dark)');
		systemDark = mq.matches;
		const on = (e: MediaQueryListEvent) => (systemDark = e.matches);
		mq.addEventListener('change', on);
		return () => mq.removeEventListener('change', on);
	});

	$effect(() => {
		const d = dark;
		if (!ready || !map) return;
		for (const id of ['esri', 'otm', 'sat']) {
			const p = basePaint(d, id === 'sat' ? 0.8 : 0.72);
			map.setPaintProperty(id, 'raster-brightness-max', p['raster-brightness-max']);
			map.setPaintProperty(id, 'raster-saturation', p['raster-saturation']);
		}
		const s = sky(d);
		if (s) map.setSky(s);
	});

	$effect(() => {
		// Offline, only OpenTopoMap is saved (Esri's terms don't allow storing its tiles),
		// so it shows at every zoom and satellite waits for a connection.
		const off = offline;
		const sat = satellite && !off;
		if (!ready || !map) return;
		map.setLayoutProperty('esri', 'visibility', sat || off ? 'none' : 'visible');
		map.setLayoutProperty('otm', 'visibility', sat ? 'none' : 'visible');
		map.setLayerZoomRange('otm', off ? 0 : DETAIL_ZOOM - 0.5, 24);
		map.setPaintProperty('otm', 'raster-opacity', off ? 1 : OTM_OPACITY);
		for (const id of ['sat', 'satlabels'])
			map.setLayoutProperty(id, 'visibility', sat ? 'visible' : 'none');
	});

	$effect(() => {
		const set = () => (offline = navigator.onLine === false);
		addEventListener('online', set);
		addEventListener('offline', set);
		return () => {
			removeEventListener('online', set);
			removeEventListener('offline', set);
		};
	});

	$effect(() => {
		const runs = runsOn;
		const peaks = peaksOn;
		if (!ready || !map) return;
		for (const id of SKI_LAYERS) map.setLayoutProperty(id, 'visibility', runs ? 'visible' : 'none');
		for (const id of PEAK_LAYERS)
			map.setLayoutProperty(id, 'visibility', peaks ? 'visible' : 'none');
	});

	// Peak heights and contours in the viewer's units; label colours with the theme.
	$effect(() => {
		const u = units;
		const d = dark;
		if (!ready || !map) return;
		map.setLayoutProperty('peak-labels', 'text-field', peakLabel(u));
		map.setPaintProperty('peak-labels', 'text-halo-color', halo(d));
		map.setPaintProperty('run-casing', 'line-color', halo(d));
		map.setPaintProperty('peak-labels', 'text-color', peakText(d));
		map.setPaintProperty('peaks', 'circle-color', peakColor(d));
		if (radar) setTerrainUnits(map, u);
	});

	// ---- Terrain layers ------------------------------------------------------------
	$effect(() => {
		const o = overlayMode;
		if (ready && map && radar) setOverlay(map, o);
	});
	$effect(() => {
		const s = prefs.mapShade;
		const d = dark;
		const b = satellite ? 'satellite' : 'topo';
		const sun = sunLight;
		if (ready && map && radar) setShade(map, s, d, b, sun);
	});
	$effect(() => {
		const c = contoursOn;
		const d = dark;
		if (ready && map && radar) setContours(map, c, d);
	});

	// ---- Sun & shade and Wind effect: one picture for the view, from the terrain worker --
	const phone = typeof matchMedia !== 'undefined' && matchMedia('(max-width: 700px)').matches;
	/** The longer side of the grid the worker works on. */
	const AREA_PX = phone ? 768 : 1024;
	const pad2 = (n: number) => String(n).padStart(2, '0');
	const today = () => {
		const d = new Date();
		return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
	};
	/** The middle of the map, as of the last time it came to rest. */
	let centre = $state({ lat: 48, lon: -120 });
	/** Counts the map coming to rest, so the picture is redone for the new view. */
	let viewTick = $state(0);
	let sunMode = $state<'shade' | 'hours'>('shade');
	let sunDate = $state(today());
	/** The time on the shade slider; 0 until first placed. */
	let sunTime = $state(0);
	let windWindow = $state<WindWindow>('next24');
	let windData = $state<MapWindOut | null>(null);
	let windLoaded = $state(false);
	let areaState = $state<AreaState>('idle');
	let analysisLayer: AnalysisLayer | null = null;
	let runner: AreaRunner | null = null;

	const sunYmd = $derived.by<Ymd>(() => {
		const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(sunDate);
		const d = new Date();
		return m ? [+m[1], +m[2], +m[3]] : [d.getFullYear(), d.getMonth() + 1, d.getDate()];
	});
	const day = $derived(sunDay(sunYmd, centre.lat, centre.lon));
	// Keep the slider inside the day: at this moment if the sun is up, else at its highest.
	$effect(() => {
		const { sunrise, sunset, noon } = day;
		if (sunrise == null || sunset == null) return;
		const step = 15 * 60000;
		if (sunTime >= sunrise && sunTime <= sunset) return;
		const now = Date.now();
		sunTime = Math.round((now > sunrise && now < sunset ? now : noon) / step) * step;
	});
	const sunPos = $derived(sunTime ? sunPosition(sunTime, centre.lat, centre.lon) : null);
	const sunOn = $derived(overlayMode === 'sun');
	const windOn = $derived(overlayMode === 'wind');
	const areaTooFar = $derived((sunOn && zoom < SUN_MIN_ZOOM) || (windOn && zoom < WIND_MIN_ZOOM));
	/** Hill shading lit from where the sun is, while the shade is showing. */
	const sunLight = $derived(
		sunOn && sunMode === 'shade' && sunPos && sunPos.altitude > 0 && !areaTooFar ? sunPos : null
	);
	const wind = $derived(windSource(windData, centre.lat, centre.lon, windWindow));

	// The locations' wind, fetched when the layer is first switched on.
	$effect(() => {
		if (!windOn || windLoaded) return;
		getMapWind()
			.then((d) => (windData = d))
			.catch((e) => console.error('wind', e))
			.finally(() => (windLoaded = true));
	});

	// Ask for the picture again whenever what it shows changes, or the map comes to rest.
	$effect(() => {
		void viewTick;
		const mode = overlayMode;
		let job: AreaJob | null = null;
		let opacity = 0.5;
		if (mode === 'sun' && !areaTooFar && day.sunrise != null && day.sunset != null) {
			if (sunMode === 'hours') {
				job = { type: 'sunhours', date: sunYmd };
				opacity = ANALYSIS_OPACITY.hours;
			} else if (sunTime) {
				job = { type: 'shade', time: sunTime };
				opacity = ANALYSIS_OPACITY.shade;
			}
		} else if (mode === 'wind' && !areaTooFar && wind?.rose && wind.scale > 0) {
			job = { type: 'wind', sectors: $state.snapshot(wind.rose.sectors), scale: wind.scale };
			opacity = ANALYSIS_OPACITY.wind;
		}
		if (!ready || !map || !runner) return;
		if (job) runner.request(job, viewBounds(map), AREA_PX, opacity);
		else runner.request(null);
	});

	// ---- Inspector: tap the map for the terrain there --------------------------------
	let probe = $state<{ lat: number; lon: number } | null>(null);
	let facts = $state<PointFacts | null>(null);
	let factsError = $state<string | null>(null);
	let probeSun = $state<SunFacts | null>(null);
	let probeWind = $state<{ value: number; window: string } | null>(null);
	let probeMarker: Marker | null = null;
	let probeToken = 0;

	async function inspect(lat: number, lon: number) {
		const c = terrainClient();
		if (!c || !map || !ml) return;
		const token = ++probeToken;
		probe = { lat, lon };
		facts = null;
		factsError = null;
		probeSun = null;
		probeWind = null;
		if (!probeMarker) {
			const dot = document.createElement('div');
			dot.className = 'probe';
			probeMarker = new ml.Marker({ element: dot, opacityWhenCovered: '1' });
		}
		probeMarker.setLngLat([lon, lat]).addTo(map);
		try {
			const f = await c.point(lat, lon);
			if (token !== probeToken) return;
			facts = f;
			if (f.sea) return;
			// Sun and wind take a little longer and join the numbers when ready; neither is
			// worth an error message if its terrain can't be had.
			c.sunPoint(lat, lon, sunYmd).then(
				(s) => token === probeToken && (probeSun = s),
				() => {}
			);
			const w = windSource(windData, lat, lon, windWindow);
			if (windOn && w?.rose && w.scale > 0) {
				const { scale } = w;
				const label = WIND_WINDOWS.find((x) => x.id === windWindow)!.label;
				c.windPoint(lat, lon, $state.snapshot(w.rose.sectors)).then(
					(v) => token === probeToken && (probeWind = { value: v * scale, window: label }),
					() => {}
				);
			}
		} catch (e) {
			if (token === probeToken)
				factsError = offline
					? 'No saved terrain here. Save this area for offline use first.'
					: `Couldn't measure the terrain here (${e instanceof Error ? e.message : e}).`;
		}
	}

	function closeInspector() {
		probeToken++;
		probe = null;
		facts = null;
		factsError = null;
		probeSun = null;
		probeWind = null;
		probeMarker?.remove();
	}

	// 3D: drape everything over the terrain and tilt the view; back to flat and north-up
	// when it's switched off.
	$effect(() => {
		const want = terrainOn;
		if (!ready || !map) return;
		if (want) {
			map.setTerrain({ source: 'dem', exaggeration: EXAGGERATION });
			// Unless a fly-to is already tilting the view.
			if (map.getPitch() < 20 && !map.isMoving()) map.easeTo({ pitch: 60, duration: 900 });
		} else {
			if (map.getTerrain()) map.setTerrain(null);
			if (map.getPitch() > 0 || map.getBearing() !== 0)
				map.easeTo({ pitch: 0, bearing: 0, duration: 700 });
		}
	});

	// The full map fills the window below the header (and any banner), edge to edge;
	// on phones and tablets the tab bar floats over it. On desktop it fills the space
	// beside the navigation rail as a rounded panel.
	let fillTop = $state(0);
	let fillLeft = $state(0);
	let fillRight = $state(0);
	$effect(() => {
		if (!radar || !wrap) return;
		const main = wrap.closest('main');
		// Whole pixels: a map placed at a fractional offset blends every tile edge,
		// which draws a faint grid.
		const measure = () => {
			const box = (main ?? wrap!).getBoundingClientRect();
			fillTop = Math.round(box.top + window.scrollY);
			fillLeft = viewport.desktop ? Math.round(box.left) : 0;
			fillRight = viewport.desktop
				? Math.max(0, Math.round(document.documentElement.clientWidth - box.right))
				: 0;
		};
		measure();
		window.addEventListener('resize', measure);
		return () => window.removeEventListener('resize', measure);
	});

	// ---- Weather timeline ------------------------------------------------------------
	// The server draws every frame; here we download them all once and swap them.
	const on = $derived(radar && prefs.mapWeather !== 'off');
	let timeline = $state<Timeline | null>(null);
	/** Why precipitation isn't showing, in words; null when it is. */
	let loadError = $state<string | null>(null);
	let frame = $state(0);
	// Radar loops play by themselves, unless the device asks for less motion.
	let playing = $state(
		typeof matchMedia === 'undefined' || !matchMedia('(prefers-reduced-motion: reduce)').matches
	);
	let now = $state(Date.now());
	/** The frame on screen (file name), which lags `frame` for the moment it takes to decode. */
	let shown = $state<string | null>(null);
	/** Frames downloaded so far. */
	let ready_ = $state<Set<string>>(new Set());

	const frames = $derived(timeline?.frames ?? []);
	const count = $derived(frames.length);
	const current = $derived<Frame | undefined>(frames[Math.min(frame, count - 1)]);
	const label = $derived(current ? frameLabel(current, now) : null);
	const waiting = $derived(!!current && shown !== current.file);

	const store = new FrameStore();
	let overlay: PrecipLayer | null = null;
	/** Which snow total is shown: its window in hours. */
	let totalWindow = $state(24);
	const totals = $derived(timeline?.totals ?? []);
	const total = $derived(
		totals.find((t) => t.window === totalWindow) ?? totals[Math.min(1, totals.length - 1)]
	);
	$effect(() => {
		const tot = totalsMode;
		if (ready && map?.getLayer(PrecipLayer.ID))
			map.setPaintProperty(PrecipLayer.ID, 'raster-opacity', tot ? TOTAL_OPACITY : PRECIP_OPACITY);
	});

	/** Put the wanted frame on screen; the old one stays until the new one is decoded. */
	let showToken = 0;
	async function show() {
		if (!map || !timeline) return;
		if (on && totalsMode && total) {
			const t = total;
			const token = ++showToken;
			const bmp = await store.bitmap(t);
			if (token !== showToken || !overlay) return;
			overlay.draw(t.file, bmp);
			shown = t.file;
			return;
		}
		if (!on || !current || totalsMode) {
			++showToken;
			overlay?.draw(null, null);
			shown = null;
			return;
		}
		const f = current;
		const token = ++showToken;
		const bmp = await store.bitmap(f);
		if (token !== showToken || !overlay) return;
		overlay.draw(f.file, bmp);
		shown = f.file;
		// Have the next one decoded before it's asked for.
		const next = frames[(frame + 1) % count];
		if (next) void store.bitmap(next);
	}

	/**
	 * Download the frames, nearest to the one on screen first. Frames beyond ~48 h wait
	 * until the slider reaches them or the page has sat idle 5 seconds, so the first paint
	 * stays a couple of MB.
	 */
	let fetchRun = 0;
	let extendedWanted = $state(false);
	let idleTimer: ReturnType<typeof setTimeout> | undefined;
	async function fetchAll() {
		const run = ++fetchRun;
		if (!timeline) return;
		const from = timeline.extendedFrom;
		const order = frames
			.map((f, i) => ({ f, i, d: Math.abs(i - frame) + (i < frame ? 0.5 : 0) }))
			.filter((x) => extendedWanted || from < 0 || x.i < from)
			.sort((a, b) => a.d - b.d)
			.map((x) => x.f);
		await Promise.all(
			order.map((f) =>
				store.blob(f).then(() => {
					// eslint-disable-next-line svelte/prefer-svelte-reactivity -- replaced wholesale
					if (run === fetchRun) ready_ = new Set(ready_).add(f.file);
				})
			)
		);
		if (run === fetchRun && !extendedWanted && from >= 0) {
			clearTimeout(idleTimer);
			idleTimer = setTimeout(() => (extendedWanted = true), 5000);
		}
	}
	// The slider entered the extended stretch: fetch it now.
	$effect(() => {
		const from = timeline?.extendedFrom ?? -1;
		if (from >= 0 && frame >= from && !totalsMode) extendedWanted = true;
	});
	$effect(() => {
		if (extendedWanted && ready) void fetchAll();
	});
	$effect(() => () => clearTimeout(idleTimer));

	async function refresh() {
		try {
			const before = current?.t;
			const atNow = !timeline || frame === timeline.now;
			const tl = await loadTimeline();
			loadError = null;
			// The pictures' box only changes when locations do.
			const sameBox = timeline && JSON.stringify(timeline.bounds) === JSON.stringify(tl.bounds);
			timeline = tl;
			store.keepOnly([...tl.frames, ...tl.totals]);
			ready_ = new Set(tl.frames.filter((f) => store.has(f)).map((f) => f.file));
			// Keep the viewer's place if that time still exists; otherwise go to "now".
			const same = tl.frames.findIndex((f) => f.t === before);
			frame = atNow || same < 0 ? Math.max(0, tl.now) : same;
			if (map && (!overlay || !sameBox)) {
				overlay?.remove();
				// Over the base map, under the satellite labels and the ski runs.
				overlay = new PrecipLayer(
					map,
					tl.bounds,
					tl.width,
					tl.height,
					totalsMode ? TOTAL_OPACITY : PRECIP_OPACITY,
					PRECIP_BEFORE
				);
			}
			void show();
			void fetchAll();
		} catch (e) {
			loadError =
				e instanceof PrecipError
					? e.message
					: `Precipitation couldn't be shown (${e instanceof Error ? e.message : e}).`;
			console.error('precipitation', e);
		}
	}

	// While it isn't showing, try again every 30 seconds (the server may be mid-build).
	$effect(() => {
		if (!loadError || !ready) return;
		const id = setTimeout(refresh, 30 * 1000);
		return () => clearTimeout(id);
	});

	$effect(() => {
		void frame;
		void on;
		void count;
		void totalsMode;
		void total;
		if (ready) void show();
	});

	// Play: step when the next frame is on hand (or after a short wait), quicker through
	// the radar, and hold a moment on "now" and on the last frame.
	$effect(() => {
		if (!ready || !playing || !on || totalsMode || count < 2) return;
		let hold = 0;
		let waits = 0;
		let loops = 0;
		let id: ReturnType<typeof setTimeout>;
		const tick = () => {
			const radarish = frames[frame]?.kind !== 'forecast';
			id = setTimeout(tick, radarish ? 300 : 450);
			if (hold > 0) return void hold--;
			const next = (frame + 1) % count;
			if ((waiting || !store.has(frames[next])) && waits++ < 10) return;
			waits = 0;
			// A few loops, then rest on "now": endless playback keeps the phone busy.
			if (next === 0 && ++loops >= 3) {
				playing = false;
				frame = Math.max(0, timeline?.now ?? 0);
				return;
			}
			frame = next;
			if (next === count - 1) hold = 4;
			else if (next === timeline?.now) hold = 3;
		};
		id = setTimeout(tick, 600);
		return () => clearTimeout(id);
	});

	// Stop playing when the app goes to the background.
	$effect(() => {
		const onHide = () => document.hidden && (playing = false);
		document.addEventListener('visibilitychange', onHide);
		return () => document.removeEventListener('visibilitychange', onHide);
	});

	$effect(() => {
		if (!radar) return;
		const ids = [
			setInterval(refresh, 5 * 60 * 1000),
			setInterval(() => (now = Date.now()), 60 * 1000)
		];
		return () => ids.forEach(clearInterval);
	});

	const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

	$effect(() => {
		if (!el) return;
		let cancelled = false;
		import('maplibre-gl').then(async (mod) => {
			if (cancelled || !el) return;
			ml = (mod as unknown as { default?: typeof mod }).default ?? mod;
			// MapLibre 6 looks for its worker next to its own file, which bundling moves;
			// point it at the copy Vite ships.
			ml.setWorkerUrl(maplibreWorker);
			// The terrain worker and contours only matter on the full map.
			const terrain = radar ? await setupTerrain(ml) : { worker: false };
			if (cancelled || !el) return;
			analysis = terrain.worker;
			const ctiles = radar ? contourTiles(units) : undefined;
			contoursReady = !!ctiles;
			map = new ml.Map({
				container: el,
				style: mapStyle({
					dark,
					full: radar,
					units,
					base: prefs.mapBase,
					runs: prefs.mapFeatures.has('runs'),
					peaks: prefs.mapFeatures.has('peaks'),
					contours: contoursOn,
					shade: prefs.mapShade,
					overlay: overlayMode,
					worker: terrain.worker,
					contourTiles: ctiles
				}),
				center: [-120, 48],
				zoom: 5,
				maxZoom: 18,
				maxPitch: 80,
				// Phones draw at 2x, not 3x: less than half the pixels, and it still looks sharp.
				pixelRatio: Math.min(devicePixelRatio, 2),
				// Fewer tiles kept in memory on phones.
				maxTileCacheSize: phone ? 60 : 160,
				attributionControl: false,
				scrollZoom: radar,
				renderWorldCopies: false,
				fadeDuration: 150
			});
			map.addControl(new ml.NavigationControl({ visualizePitch: true }), 'top-left');
			map.addControl(
				new ml.AttributionControl({
					compact: true,
					customAttribution:
						'Weather: <a href="https://open-meteo.com/">Open-Meteo</a> (CC BY 4.0), NWS, NRCS SNOTEL'
				}),
				'top-right'
			);
			map.on('zoom', () => (zoom = map!.getZoom()));
			// The map came to rest: the view's sun or wind picture is redone a moment later.
			let rest: ReturnType<typeof setTimeout>;
			map.on('moveend', () => {
				clearTimeout(rest);
				rest = setTimeout(() => {
					if (!map) return;
					const c = map.getCenter();
					centre = { lat: c.lat, lon: c.lng };
					viewTick++;
				}, 250);
			});
			// The "3D view" buttons inside marker popups.
			el.addEventListener('click', (e) => {
				const id = (e.target as HTMLElement).closest<HTMLElement>('[data-fly]')?.dataset.fly;
				if (id) flyTo(id);
			});
			// Tilting by hand switches 3D on: a tilted flat map is just a stretched map.
			map.on('pitchend', () => {
				if (radar && map!.getPitch() > 10 && prefs.mapTerrain !== 'on') prefs.setMapTerrain(true);
			});
			// A tap on the map itself (not a marker or a popup) asks what the terrain is there.
			map.on('click', (e) => {
				if (!radar || !analysis) return;
				if (popups.some((p) => p.isOpen())) {
					for (const p of popups) p.remove();
					return;
				}
				if (panel !== 'none') {
					panel = 'none';
					return;
				}
				void inspect(e.lngLat.lat, e.lngLat.lng);
			});
			map.on('load', () => {
				if (cancelled) return;
				// Credits start folded to their (i) button, which opens them.
				el?.querySelector('.maplibregl-ctrl-attrib')?.classList.remove('maplibregl-compact-show');
				zoom = map!.getZoom();
				if (radar && canLocate) {
					loc = new UserLocation(map!, ml!);
					loc.onChange = (st) => (locState = st);
				}
				const tc = radar && analysis ? terrainClient() : null;
				if (tc) {
					// Over the terrain overlays, under the precipitation (added later, above it).
					analysisLayer = new AnalysisLayer(map!, PRECIP_BEFORE);
					runner = new AreaRunner(tc, analysisLayer);
					runner.onstate = (st) => (areaState = st);
				}
				ready = true;
				draw();
				const c = map!.getCenter();
				centre = { lat: c.lat, lon: c.lng };
				if (radar) refresh();
			});
		});
		return () => {
			cancelled = true;
			loc?.stop();
			loc = null;
			ready = false;
			fetchRun++;
			runner?.stop();
			runner = null;
			analysisLayer = null;
			overlay = null;
			store.clear();
			for (const m of markers) m.remove();
			markers = [];
			probeMarker?.remove();
			probeMarker = null;
			map?.remove();
			map = null;
		};
	});

	$effect(() => {
		void rows;
		void units;
		draw();
	});

	/** Fly to a location, tilted, in 3D: the quickest way to look at its terrain. */
	function flyTo(id: string) {
		const r = rows.find((x) => x.id === id);
		if (!map || !r || r.lat == null || r.lon == null) return;
		prefs.setMapTerrain(true);
		for (const p of popups) p.remove();
		map.flyTo({
			center: [r.lon, r.lat],
			zoom: 13.5,
			pitch: 65,
			bearing: map.getBearing() || -20,
			duration: 2600
			// Not "essential": MapLibre then jumps instead when the device asks for less motion.
		});
	}

	let fitted = false;
	function draw() {
		if (!map || !ml || !ready) return;
		for (const m of markers) m.remove();
		for (const p of popups) p.remove();
		markers = [];
		popups = [];
		const placed = rows.filter((r) => r.lat !== null && r.lat !== undefined && r.lon != null);
		for (const r of placed) {
			const b = bucket(r.next5_cm);
			const danger = r.danger?.status === 'current' && r.danger.level ? r.danger.level : 0;
			const label = snowNum(r.next5_cm, units);
			// The pin opens its own popup (click, Enter or Space): MapLibre's built-in
			// toggle listens for map clicks, which don't arrive reliably over markers.
			const pin = document.createElement('div');
			pin.className = 'snowpin';
			pin.tabIndex = 0;
			pin.setAttribute('role', 'button');
			pin.title = r.name;
			pin.setAttribute('aria-label', `${r.name}: ${label} ${units === 'imperial' ? 'in' : 'cm'}`);
			pin.innerHTML = `<span class="dot b${b}${danger ? ` ring d${danger}` : ''}">${esc(label)}</span>`;
			const unit = units === 'imperial' ? 'in' : 'cm';
			const dangerLine = danger ? `<div>Avalanche ${danger} · ${dangerWord(danger)}</div>` : '';
			const popup = new ml.Popup({ offset: 20, maxWidth: '240px' }).setHTML(
				`<strong>${esc(r.name)}</strong><div>${esc(label)} ${unit} in the next 5 days</div>` +
					`${dangerLine}<div class="pop-actions"><a href="${esc(href(r.id))}">Open forecast →</a>` +
					`<button type="button" data-fly="${esc(r.id)}">3D view</button></div>`
			);
			popups.push(popup);
			const toggle = () => {
				if (popup.isOpen()) popup.remove();
				else {
					for (const other of popups) other.remove();
					popup.setLngLat([r.lon!, r.lat!]).addTo(map!);
				}
			};
			pin.addEventListener('click', (e) => {
				e.stopPropagation();
				toggle();
			});
			pin.addEventListener('keydown', (e) => {
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					toggle();
				}
			});
			markers.push(
				// Always fully shown: in 3D, MapLibre would dim a marker it thinks a ridge hides.
				new ml.Marker({ element: pin, opacityWhenCovered: '1' })
					.setLngLat([r.lon!, r.lat!])
					.addTo(map)
			);
		}
		// Frame the locations once; after that the view is the viewer's.
		if (placed.length && !fitted) {
			fitted = true;
			const lons = placed.map((r) => r.lon!);
			const lats = placed.map((r) => r.lat!);
			map.fitBounds(
				[
					[Math.min(...lons), Math.min(...lats)],
					[Math.max(...lons), Math.max(...lats)]
				],
				{ padding: 70, maxZoom: 9, animate: false }
			);
		}
	}

	const unit = $derived(units === 'imperial' ? 'in' : 'cm');
	const source = $derived(current ? frameSource(current) : '');
	const radarShown = $derived(!!current && current.kind !== 'forecast');
</script>

<svelte:window
	onkeydown={(e) =>
		e.key === 'Escape' && (panel !== 'none' ? (panel = 'none') : probe && closeInspector())}
/>

<div
	class="wrap"
	class:fill={radar}
	class:panel={radar && viewport.desktop}
	class:dark
	bind:this={wrap}
	style:--fill-top="{fillTop}px"
	style:--fill-left="{fillLeft}px"
	style:--fill-right="{fillRight}px"
>
	<div class="map" bind:this={el} role="region" aria-label="Map of locations"></div>

	{#if radar}
		<div class="tools">
			{#if canLocate}
				<button
					class="tool"
					class:active={locState === 'following'}
					class:shown={locState === 'shown' || locState === 'locating'}
					aria-pressed={locState === 'following' || locState === 'shown'}
					onclick={() => loc?.toggle()}
					title={locState === 'following'
						? 'Stop showing your location'
						: locState === 'shown'
							? 'Back to your location'
							: 'Show your location'}
					aria-label="Your location"
				>
					<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
						><path d="M20 4L4 11l7 2 2 7 7-16z" class:fill={locState === 'following'} /></svg
					>
				</button>
			{/if}
			<button
				class="tool three"
				class:active={terrainOn}
				aria-pressed={terrainOn}
				onclick={() => prefs.setMapTerrain(!terrainOn)}
				title={terrainOn
					? 'Back to a flat map'
					: '3D terrain: tilt with two fingers or right-drag, turn by twisting or Ctrl-drag'}
				aria-label="3D terrain">3D</button
			>
			<button
				class="tool"
				class:active={panel === 'layers'}
				aria-expanded={panel === 'layers'}
				aria-controls="map-layers"
				onclick={() => togglePanel('layers')}
				title="Base map, weather, terrain and what's shown"
				aria-label="Layers"
			>
				<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
					><path d="M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5" /></svg
				>
			</button>
			<button
				class="tool"
				class:active={panel === 'offline'}
				aria-expanded={panel === 'offline'}
				onclick={() => togglePanel('offline')}
				title="Save maps for use with no signal"
				aria-label="Offline maps"
			>
				<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
					><path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19h14" /></svg
				>
			</button>
			<button
				class="tool"
				class:active={panel === 'info'}
				aria-expanded={panel === 'info'}
				aria-controls="map-info"
				onclick={() => togglePanel('info')}
				aria-label="About this map"
			>
				<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
					><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></svg
				>
			</button>
		</div>

		{#if panel === 'layers'}
			<LayersSheet {analysis} contours={contoursReady} {offline} onclose={() => (panel = 'none')} />
		{/if}

		{#if panel === 'offline'}
			<OfflineMaps
				places={rows
					.filter((r) => r.lat != null && r.lon != null)
					.map((r) => ({ id: r.id, name: r.name, lat: r.lat!, lon: r.lon! }))}
				onclose={() => (panel = 'none')}
			/>
		{/if}

		<Legend overlay={overlayMode} {units} {zoom} />

		<div class="top">
			{#if locState === 'locating' || locState === 'denied' || locState === 'unavailable' || offline || (on && tooClose)}
				<p class="note glass" role="status">
					{#if on && tooClose && !offline && locState !== 'locating' && locState !== 'denied' && locState !== 'unavailable'}
						Zoom out to see {totalsMode ? 'snow totals' : 'precipitation'}.
					{/if}
					{#if offline}
						Offline: showing saved maps.
					{/if}
					{#if locState === 'locating'}
						Finding you…
					{:else if locState === 'denied'}
						Location is off for this site. On iPhone: Settings → Privacy & Security → Location
						Services → Safari Websites → While Using.
					{:else if locState === 'unavailable'}
						No GPS fix yet. Keep the phone where it can see the sky.
					{/if}
				</p>
			{/if}
			{#if probe}
				<Inspector
					lat={probe.lat}
					lon={probe.lon}
					{facts}
					error={factsError}
					{units}
					sun={probeSun}
					wind={probeWind}
					onclose={closeInspector}
				/>
			{/if}
		</div>

		{#if panel === 'info'}
			<div class="info" role="dialog" aria-label="About this map" id="map-info">
				<p class="item">
					<span class="pin" aria-hidden="true">1.2</span> Next 5 days of snow ({unit}). Tap one for
					details.
				</p>
				<p class="item">
					<span class="pin ring" aria-hidden="true"></span> Ring: avalanche danger, when rated.
				</p>
				{#if on}
					<p>{radarShown ? `${source} ${RADAR_GAPS}` : source}</p>
					<p>
						Darkest shades: snow {rampTop(RAMPS.snow, units)}, rain {rampTop(RAMPS.rain, units)}.
					</p>
					<p class="faint">
						Snow per hour assumes about 10 parts snow to 1 part water. Beyond about two days the
						frames are 3- and 6-hour averages, and forecasts get rougher the further out they go.
					</p>
					<p class="faint">
						Snow total: Canadian models in Canada (HRDPS, then RDPS, then GDPS), with the snow ratio
						from the forecast temperature; NOAA's National Blend of Models in the US; blended across
						the border.
						{#if totalsMode && total}{totalSources(total)}{/if}
					</p>
				{/if}
				<p class="faint">
					Terrain: elevation from Mapterhorn (US lidar to 1 m, Canadian lidar to 2 m, 10–30 m
					elsewhere). Slope and aspect are worked out on this device from about 10 m terrain, so
					small features like cornices and gully walls don't show. Tap the map for the numbers at a
					spot.
				</p>
				<p class="faint">
					Sun & shade: the sun's position by NOAA's formulas, and shadows cast by terrain up to 15
					km away. Wind effect: how sheltered each slope is from the forecast wind at the nearest
					location's summit, weighted by the snow that wind could move. Both are estimates from the
					shape of the ground, not observations, and say nothing about how stable the snow is.
				</p>
				<button class="close" onclick={() => (panel = 'none')}>Close</button>
			</div>
		{/if}

		<div class="dock">
			{#if (sunOn || windOn) && analysis}
				<TerrainControls
					overlay={sunOn ? 'sun' : 'wind'}
					{units}
					tooFar={areaTooFar}
					state={areaState}
					{offline}
					bind:sunMode
					bind:sunDate
					bind:sunTime
					{day}
					position={sunPos}
					bind:windWindow
					{wind}
					{windLoaded}
				/>
			{/if}
			{#if on}
				<TimelineControls
					{timeline}
					{units}
					{totalsMode}
					bind:frame
					bind:playing
					bind:totalWindow
					{total}
					{current}
					{label}
					{waiting}
					ready={ready_}
					{loadError}
				/>
			{/if}
		</div>
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
		/* Keep the map's layers inside, under the floating tab bar. */
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
	/* The full map: the whole window below the header, edge to edge. */
	.wrap.fill {
		position: fixed;
		top: var(--fill-top);
		left: 0;
		right: 0;
		bottom: 0;
	}
	.fill .map {
		height: 100%;
		border-radius: 0;
		border: 0;
	}
	/* Desktop: a rounded panel beside the rail. */
	.wrap.fill.panel {
		left: var(--fill-left);
		right: var(--fill-right);
		bottom: 14px;
	}
	.panel .map {
		border-radius: 28px;
		border: 1px solid var(--panel-rim);
		box-shadow: var(--shadow);
	}
	/* MapLibre's controls: credits as a small (i) in the top-right, and room for our
	   buttons under the zoom and compass. */
	.map :global(.maplibregl-ctrl-attrib) {
		font-size: 0.65rem;
	}
	.map :global(.maplibregl-popup-content) {
		font: inherit;
		font-size: 0.85rem;
		border-radius: 10px;
		padding: 10px 14px;
		color: #1f1b2e;
	}
	.map :global(.maplibregl-popup-content a) {
		color: #4b3fb5;
		font-weight: 600;
	}
	.map :global(.pop-actions) {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 6px;
	}
	.map :global(.pop-actions button) {
		border: 0;
		border-radius: 999px;
		padding: 4px 10px;
		background: #4b3fb5;
		color: #fff;
		font: 600 0.8rem/1.2 inherit;
		cursor: pointer;
	}

	/* MapLibre's zoom and compass buttons, as a glass column like ours. */
	.map :global(.maplibregl-ctrl-top-left .maplibregl-ctrl-group) {
		margin: 10px 0 0 10px;
		border-radius: 14px;
		overflow: hidden;
		background: var(--glass);
		border: 1px solid var(--glass-border);
		box-shadow: var(--glass-shadow-sm);
		backdrop-filter: var(--blur-glass);
		-webkit-backdrop-filter: var(--blur-glass);
	}
	.map :global(.maplibregl-ctrl-top-left .maplibregl-ctrl-group button) {
		width: 40px;
		height: 38px;
		background-color: transparent;
	}
	.map :global(.maplibregl-ctrl-top-left .maplibregl-ctrl-group button + button) {
		border-top: 1px solid var(--grid);
	}
	.map :global(.maplibregl-ctrl-top-left .maplibregl-ctrl-group button:hover) {
		background-color: var(--hover);
	}
	/* Its icons are dark drawings: lighten them on dark glass. */
	:global(:root[data-mode='dark']) .map :global(.maplibregl-ctrl-icon) {
		filter: invert(1) brightness(1.6);
	}

	/* The controls at the foot of the map: terrain (when its layer has any) over weather. */
	.dock {
		position: absolute;
		left: 10px;
		right: 10px;
		bottom: 10px;
		z-index: 1000;
		display: grid;
		gap: 8px;
		justify-items: center;
		pointer-events: none;
	}
	.dock > :global(*) {
		width: 100%;
		max-width: 640px;
		pointer-events: auto;
	}
	/* Clear the floating tab bar on phones. */
	@media (max-width: 1099px) {
		.dock {
			bottom: calc(84px + env(safe-area-inset-bottom));
		}
	}
	.tools {
		position: absolute;
		top: 136px;
		left: 10px;
		z-index: 1000;
		display: grid;
		gap: 8px;
	}
	/* Our own map buttons: glass tiles that light up in the accent when on. */
	.tool {
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		border-radius: 14px;
		border: 1px solid var(--glass-border);
		background: var(--glass);
		box-shadow: var(--glass-shadow-sm);
		backdrop-filter: var(--blur-glass);
		-webkit-backdrop-filter: var(--blur-glass);
		color: var(--text);
		cursor: pointer;
		transition:
			background-color var(--ease),
			transform 160ms ease;
	}
	.tool:hover {
		background-color: var(--hover);
	}
	.tool:active {
		transform: scale(0.94);
	}
	.tool.three {
		font: 700 0.8rem/1 var(--font-num, sans-serif);
	}
	.tool.active {
		background: var(--accent);
		border-color: transparent;
		color: var(--on-accent);
	}
	.tool.shown {
		color: var(--accent-ink);
	}
	.tool svg .fill {
		fill: currentColor;
	}
	/* Notes and the inspector: a column at the top centre, clear of the side controls. */
	.top {
		position: absolute;
		top: 10px;
		left: 60px;
		right: 54px;
		z-index: 1001;
		display: grid;
		justify-items: center;
		gap: 8px;
		pointer-events: none;
	}
	.note {
		max-width: 420px;
		margin: 0;
		padding: 8px 12px;
		border-radius: 12px;
		font-size: 0.8rem;
		text-align: center;
		color: var(--text);
		pointer-events: auto;
	}
	/* Phones: the inspector spans the top, so the terrain key steps aside while it's open. */
	@media (max-width: 700px) {
		.wrap:has(:global(.insp)) :global(.legend) {
			display: none;
		}
	}
	/* The spot the inspector is describing. */
	:global(.probe) {
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: var(--accent);
		border: 3px solid #fff;
		box-shadow: 0 1px 4px rgb(0 0 0 / 0.45);
	}
	:global(.userloc) {
		width: 22px;
		height: 22px;
		position: relative;
	}
	:global(.userloc .me) {
		position: absolute;
		inset: 3px;
		border-radius: 50%;
		background: #1a73e8;
		border: 2.5px solid #fff;
		box-shadow: 0 1px 4px rgb(0 0 0 / 0.4);
	}
	/* The way you're facing: a soft wedge pointing up, turned with the marker. */
	:global(.userloc .cone) {
		display: none;
		position: absolute;
		left: -19px;
		top: -49px;
		width: 60px;
		height: 60px;
		background: conic-gradient(
			from -30deg at 50% 100%,
			rgb(26 115 232 / 0.45),
			rgb(26 115 232 / 0) 60deg,
			transparent 60deg
		);
		clip-path: polygon(50% 100%, 0 0, 100% 0);
		mask: radial-gradient(circle at 50% 100%, #000 30%, transparent 100%);
	}
	:global(.userloc.has-heading .cone) {
		display: block;
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
		top: 136px;
		left: 60px;
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
	:global(.snowpin) {
		border: 0;
		padding: 0;
		background: none;
		cursor: pointer;
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
