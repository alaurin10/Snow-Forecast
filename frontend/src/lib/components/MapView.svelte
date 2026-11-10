<!--
  Every location on a map. Each marker shows the next-5-day snow on the
  Calendar's colour ramp, with a ring in the avalanche danger colour when the
  center's rating is current. Tap a marker for the numbers and a link.
  With `radar`, the map fills the window and precipitation plays over it on one
  timeline: the last three hours of observed radar, a 72-minute radar nowcast, then the
  next ~48 hours of forecast
  (see ../radar.ts). It's a MapLibre map: tilt and turn it, and switch on 3D terrain.
-->
<script lang="ts">
	import 'maplibre-gl/dist/maplibre-gl.css';
	import maplibreWorker from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
	import type {
		ExpressionSpecification,
		Map as MlMap,
		Marker,
		Popup,
		StyleSpecification
	} from 'maplibre-gl';
	import type { OverviewRow } from '../types.gen';
	import { bucket } from '../calendar';
	import { dangerWord } from '../conditions';
	import { snowNum, type UnitSystem } from '../units';
	import { prefs } from '../prefs.svelte';
	import {
		frameLabel,
		frameSource,
		loadTimeline,
		PrecipError,
		RADAR_GAPS,
		RAMPS,
		rampTop,
		TOTAL,
		totalSpan,
		totalTick,
		UNTYPED,
		untypedTop,
		type Frame,
		type Timeline
	} from '../radar';
	import { FrameStore, PrecipLayer } from '../precipOverlay';
	import { UserLocation, type LocState } from '../userLocation';
	import OfflineMaps from './OfflineMaps.svelte';

	interface Props {
		rows: OverviewRow[];
		units: UnitSystem;
		href: (id: string) => string;
		/** The full map: precipitation, its controls, and the whole window. */
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
	let infoOpen = $state(false);
	let offlineOpen = $state(false);
	let loc: UserLocation | null = null;
	let locState = $state<LocState>('off');
	const canLocate = UserLocation.supported();
	/** No connection: the map shows only what's saved (OpenTopoMap at every zoom). */
	let offline = $state(typeof navigator !== 'undefined' && navigator.onLine === false);
	let zoom = $state(0);

	/** From here in, OpenTopoMap's detail (contours, trails, peaks, lifts) takes over. */
	const DETAIL_ZOOM = 12;
	const PISTE_ZOOM = 11;
	/** A little extra height reads well zoomed out without making couloirs cartoonish up close. */
	const EXAGGERATION = 1.15;
	const pistesOn = $derived(radar && prefs.mapPistes === 'on');
	const terrainOn = $derived(radar && prefs.mapTerrain === 'on');
	const satellite = $derived(radar && prefs.mapBase === 'satellite');
	// The precipitation pictures are ~1.4 km a pixel: they fade as the map zooms past
	// that and are gone up close, where one pixel would fill the screen.
	const totalsMode = $derived(radar && prefs.mapMode === 'totals');
	/** Snow totals are smooth fields: they stay on further in than the hourly frames. */
	const tooClose = $derived(zoom >= (totalsMode ? 15 : 13));
	const TOTAL_OPACITY: ExpressionSpecification = [
		'interpolate',
		['linear'],
		['zoom'],
		10,
		0.72,
		13,
		0.5,
		15,
		0
	];
	const PRECIP_OPACITY: ExpressionSpecification = [
		'interpolate',
		['linear'],
		['zoom'],
		10,
		0.8,
		11,
		0.65,
		12,
		0.4,
		13,
		0
	];

	/** Cross-fade from Esri over half a zoom level. */
	const OTM_OPACITY: ExpressionSpecification = [
		'interpolate',
		['linear'],
		['zoom'],
		DETAIL_ZOOM - 0.5,
		0,
		DETAIL_ZOOM + 0.3,
		1
	];

	// Base map and ski-run tiles come through the server, which caches them.
	const tiles = (layer: string) => [`/api/tiles/${layer}/{z}/{x}/{y}.png`];

	function mapStyle(dark: boolean): StyleSpecification {
		return {
			version: 8,
			sources: {
				esri: {
					type: 'raster',
					tiles: tiles('esri'),
					tileSize: 256,
					maxzoom: 17,
					attribution:
						'Map © <a href="https://www.esri.com">Esri</a>, HERE, Garmin, USGS, NGA, EPA, USDA, NPS'
				},
				otm: {
					type: 'raster',
					tiles: tiles('otm'),
					tileSize: 256,
					maxzoom: 17,
					attribution:
						'© <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>, SRTM | <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'
				},
				sat: {
					type: 'raster',
					tiles: tiles('sat'),
					tileSize: 256,
					maxzoom: 18,
					attribution:
						'Imagery © <a href="https://www.esri.com">Esri</a>, Maxar, Earthstar Geographics, USDA, USGS'
				},
				satlabels: {
					type: 'raster',
					tiles: tiles('satlabels'),
					tileSize: 256,
					maxzoom: 18,
					attribution: 'Labels © <a href="https://www.esri.com">Esri</a>'
				},
				// Runs, lifts and peaks from OpenStreetMap, fetched weekly by the server.
				ski: {
					type: 'geojson',
					data: '/api/osm/ski.geojson',
					attribution:
						'Runs, lifts, peaks © <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>'
				},
				// Elevation for 3D, straight from AWS (fast, and big enough not to proxy).
				dem: {
					type: 'raster-dem',
					tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
					encoding: 'terrarium',
					tileSize: 256,
					// Down to ~3 m a pixel (zoom 15, the finest these tiles have): enough to
					// see couloirs. Only the tiles in view load, so memory stays bounded.
					maxzoom: 15,
					attribution:
						'Terrain: <a href="https://registry.opendata.aws/terrain-tiles/">Mapzen, AWS</a>'
				}
			},
			layers: [
				{
					id: 'esri',
					type: 'raster',
					source: 'esri',
					maxzoom: DETAIL_ZOOM + 1,
					layout: { visibility: baseVis('topo') },
					paint: { 'raster-fade-duration': 150, ...basePaint(dark) }
				},
				{
					id: 'otm',
					type: 'raster',
					source: 'otm',
					minzoom: DETAIL_ZOOM - 0.5,
					layout: { visibility: baseVis('topo') },
					paint: {
						'raster-opacity': OTM_OPACITY,
						'raster-fade-duration': 150,
						...basePaint(dark)
					}
				},
				// Satellite: imagery, then place names and borders over it (and over the
				// precipitation, so names stay readable).
				{
					id: 'sat',
					type: 'raster',
					source: 'sat',
					layout: { visibility: baseVis('satellite') },
					paint: { 'raster-fade-duration': 150, ...basePaint(dark, 0.8) }
				},
				{
					id: 'satlabels',
					type: 'raster',
					source: 'satlabels',
					layout: { visibility: baseVis('satellite') },
					paint: { 'raster-fade-duration': 150 }
				},
				...skiLayers(dark)
			],
			glyphs: '/api/glyphs/{fontstack}/{range}.pbf',
			sky: {
				'sky-color': dark ? '#0d1626' : '#9cc6ec',
				'horizon-color': dark ? '#2a3a52' : '#e4eef7',
				'fog-color': dark ? '#1b2638' : '#dfe8f0',
				'sky-horizon-blend': 0.6,
				'horizon-fog-blend': 0.6,
				'fog-ground-blend': 0.8,
				'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 10, 1, 12, 0]
			}
		};
	}

	// ---- Runs, lifts and peaks (vector, so names follow the runs and stay upright) -----
	const RUN = ['==', ['get', 'kind'], 'run'] as const;
	const runColor: ExpressionSpecification = [
		'match',
		['get', 'difficulty'],
		['novice', 'easy'],
		'#2f9e44',
		'intermediate',
		'#1f6fd6',
		['advanced'],
		'#111111',
		['expert', 'extreme'],
		'#111111',
		'freeride',
		'#e8862a',
		['match', ['get', 'type'], ['skitour', 'backcountry'], '#7b3fb0', '#5b6b7a']
	];
	const FONT = ['Open Sans Semibold'];
	// Run and lift names keep a white outline in both themes: the difficulty colours
	// (black runs especially) are only readable on a light edge.
	const LABEL_HALO = 'rgba(255,255,255,0.95)';
	const LABEL_PAINT = {
		'text-halo-color': LABEL_HALO,
		'text-halo-width': 2,
		'text-halo-blur': 0.2
	};
	const SKI_LAYERS = ['run-casing', 'runs', 'lifts', 'run-labels', 'lift-labels'];

	function peakLabel(): ExpressionSpecification {
		const ft = units === 'imperial';
		return [
			'case',
			['has', 'ele'],
			[
				'format',
				['get', 'name'],
				{},
				'\n',
				{},
				[
					'concat',
					[
						'number-format',
						['round', ft ? ['*', ['get', 'ele'], 3.28084] : ['get', 'ele']],
						{ 'max-fraction-digits': 0 }
					],
					ft ? ' ft' : ' m'
				],
				{ 'font-scale': 0.85 }
			],
			['get', 'name']
		] as ExpressionSpecification;
	}

	function skiLayers(dark: boolean): StyleSpecification['layers'] {
		const vis = radar && prefs.mapPistes === 'on' ? 'visible' : 'none';
		const halo = dark ? 'rgba(10,15,25,0.85)' : 'rgba(255,255,255,0.9)';
		// Zoom may only feed a top-level interpolate, so the casing gets its own stops.
		const lineWidth = (add: number): ExpressionSpecification => [
			'interpolate',
			['linear'],
			['zoom'],
			11,
			1 + add,
			14,
			2.2 + add,
			17,
			4 + add
		];
		const width = lineWidth(0);
		return [
			{
				id: 'run-casing',
				type: 'line',
				source: 'ski',
				minzoom: PISTE_ZOOM,
				filter: RUN as unknown as ExpressionSpecification,
				layout: { visibility: vis, 'line-cap': 'round', 'line-join': 'round' },
				paint: { 'line-color': halo, 'line-width': lineWidth(2) }
			},
			{
				id: 'runs',
				type: 'line',
				source: 'ski',
				minzoom: PISTE_ZOOM,
				filter: RUN as unknown as ExpressionSpecification,
				layout: { visibility: vis, 'line-cap': 'round', 'line-join': 'round' },
				paint: {
					'line-color': runColor,
					'line-width': width,
					// Touring and backcountry routes dashed, like on paper maps.
					'line-dasharray': [
						'match',
						['get', 'type'],
						['skitour', 'backcountry', 'nordic', 'hike'],
						['literal', [2, 1.5]],
						['literal', [1, 0]]
					] as unknown as number[]
				}
			},
			{
				id: 'lifts',
				type: 'line',
				source: 'ski',
				minzoom: PISTE_ZOOM,
				filter: ['==', ['get', 'kind'], 'lift'],
				layout: { visibility: vis },
				paint: {
					'line-color': '#d6303a',
					'line-width': ['interpolate', ['linear'], ['zoom'], 11, 1, 16, 2.5]
				}
			},
			{
				id: 'run-labels',
				type: 'symbol',
				source: 'ski',
				minzoom: 13,
				filter: ['all', RUN as unknown as ExpressionSpecification, ['!=', ['get', 'name'], '']],
				layout: {
					visibility: vis,
					'symbol-placement': 'line',
					'text-field': ['get', 'name'],
					'text-font': FONT,
					'text-size': ['interpolate', ['linear'], ['zoom'], 13, 11.5, 17, 15],
					// Face the viewer when tilted, so names on steep runs stay readable.
					'text-pitch-alignment': 'viewport',
					'text-letter-spacing': 0.02,
					'symbol-spacing': 280,
					'text-max-angle': 35,
					// Beside the run rather than on it, so a dark line doesn't swallow the name.
					'text-offset': [0, -0.9]
				},
				paint: { 'text-color': runColor, ...LABEL_PAINT }
			},
			{
				id: 'lift-labels',
				type: 'symbol',
				source: 'ski',
				minzoom: 14,
				filter: ['all', ['==', ['get', 'kind'], 'lift'], ['!=', ['get', 'name'], '']],
				layout: {
					visibility: vis,
					'symbol-placement': 'line',
					'text-field': ['get', 'name'],
					'text-font': FONT,
					'text-size': 12,
					'text-pitch-alignment': 'viewport',
					'text-offset': [0, -0.85]
				},
				paint: { 'text-color': '#b0202a', ...LABEL_PAINT }
			},
			{
				id: 'peaks',
				type: 'circle',
				source: 'ski',
				minzoom: 10,
				filter: ['==', ['get', 'kind'], 'peak'],
				paint: {
					'circle-radius': 3,
					'circle-color': dark ? '#e8edf5' : '#3a3346',
					'circle-stroke-width': 1.2,
					'circle-stroke-color': halo
				}
			},
			{
				id: 'peak-labels',
				type: 'symbol',
				source: 'ski',
				minzoom: 10,
				filter: ['==', ['get', 'kind'], 'peak'],
				layout: {
					'text-field': peakLabel(),
					'text-font': FONT,
					'text-size': ['interpolate', ['linear'], ['zoom'], 10, 10.5, 15, 13],
					'text-anchor': 'top',
					'text-offset': [0, 0.5],
					'text-max-width': 8
				},
				paint: {
					'text-color': dark ? '#eef2f8' : '#2a2433',
					'text-halo-color': halo,
					'text-halo-width': 1.6
				}
			}
		];
	}

	function baseVis(base: 'topo' | 'satellite'): 'visible' | 'none' {
		const want = radar ? prefs.mapBase : 'topo';
		return want === base ? 'visible' : 'none';
	}

	/** Dimmed a little in the dark theme so the map doesn't glare. */
	function basePaint(dark: boolean, darkBrightness = 0.72) {
		return {
			'raster-brightness-max': dark ? darkBrightness : 1,
			'raster-saturation': dark ? -0.15 : 0
		} as const;
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
		const sky = mapStyle(d).sky;
		if (sky) map.setSky(sky);
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
		const want = pistesOn;
		if (!ready || !map) return;
		for (const id of SKI_LAYERS) map.setLayoutProperty(id, 'visibility', want ? 'visible' : 'none');
	});

	// Peak heights in the viewer's units; label colours with the theme.
	$effect(() => {
		void units;
		const d = dark;
		if (!ready || !map) return;
		map.setLayoutProperty('peak-labels', 'text-field', peakLabel());
		const halo = d ? 'rgba(10,15,25,0.85)' : 'rgba(255,255,255,0.9)';
		map.setPaintProperty('peak-labels', 'text-halo-color', halo);
		map.setPaintProperty('run-casing', 'line-color', halo);
		map.setPaintProperty('peak-labels', 'text-color', d ? '#eef2f8' : '#2a2433');
		map.setPaintProperty('peaks', 'circle-color', d ? '#e8edf5' : '#3a3346');
	});

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
	// on phones the tab bar floats over it.
	let fillTop = $state(0);
	$effect(() => {
		if (!radar || !wrap) return;
		const main = wrap.closest('main');
		// Whole pixels: a map placed at a fractional offset blends every tile edge,
		// which draws a faint grid.
		const measure = () =>
			(fillTop = Math.round((main ?? wrap!).getBoundingClientRect().top + window.scrollY));
		measure();
		window.addEventListener('resize', measure);
		return () => window.removeEventListener('resize', measure);
	});

	// ---- Precipitation timeline ------------------------------------------------
	// The server draws every frame; here we download them all once and swap them.
	const on = $derived(radar && prefs.mapPrecip === 'on');
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
	const untypedShown = $derived(current?.south === 'wpc');
	const pct = (i: number) => (count > 1 ? (i / (count - 1)) * 100 : 0);
	// Under the slider: "Now" where the radar ends, then each new day of the forecast.
	const ticks = $derived.by(() => {
		const out: { at: number; name: string; now?: boolean }[] = [];
		const nowAt = timeline?.now ?? -1;
		if (nowAt >= 0 && nowAt < count - 1) out.push({ at: pct(nowAt), name: 'Now', now: true });
		frames.forEach((f, i) => {
			if (f.kind !== 'forecast' || i === 0) return;
			const start = new Date((f.t - 3600) * 1000);
			// Skip a day name that would crowd "Now".
			if (start.getHours() === 0 && !(out[0]?.now && pct(i) - out[0].at < 10))
				out.push({ at: pct(i), name: start.toLocaleDateString('en-US', { weekday: 'short' }) });
		});
		return out;
	});
	// The nowcast's stretch of the slider, between the radar and the forecast.
	const nowcastBand = $derived.by(() => {
		const from = timeline?.now ?? -1;
		const to = timeline?.nowcastEnd ?? -1;
		if (from < 0 || to <= from) return null;
		return { left: pct(from), width: pct(to) - pct(from) };
	});
	// The slider track: downloaded frames shaded, like a video's buffered range.
	const buffered = $derived.by(() => {
		if (count < 2 || ready_.size >= count) return 'none';
		const w = 100 / (count - 1);
		const stops: string[] = [];
		frames.forEach((f, i) => {
			const c = ready_.has(f.file) ? 'var(--buffered)' : 'transparent';
			stops.push(`${c} ${Math.max(0, (i - 0.5) * w)}%`, `${c} ${Math.min(100, (i + 0.5) * w)}%`);
		});
		return `linear-gradient(90deg, ${stops.join(', ')})`;
	});

	const store = new FrameStore();
	let overlay: PrecipLayer | null = null;
	/** Which snow total is shown: its window in hours. */
	let totalHours = $state(24);
	const totals = $derived(timeline?.totals ?? []);
	const total = $derived(
		totals.find((t) => t.hours === totalHours) ?? totals[Math.min(1, totals.length - 1)]
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

	/** Download every frame, nearest to the one on screen first. */
	let fetchRun = 0;
	async function fetchAll() {
		const run = ++fetchRun;
		if (!timeline) return;
		const order = frames
			.map((f, i) => ({ f, d: Math.abs(i - frame) + (i < frame ? 0.5 : 0) }))
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
	}

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
					'satlabels'
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
		import('maplibre-gl').then((mod) => {
			if (cancelled || !el) return;
			ml = (mod as unknown as { default?: typeof mod }).default ?? mod;
			// MapLibre 6 looks for its worker next to its own file, which bundling moves;
			// point it at the copy Vite ships.
			ml.setWorkerUrl(maplibreWorker);
			const phone = matchMedia('(max-width: 700px)').matches;
			map = new ml.Map({
				container: el,
				style: mapStyle(dark),
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
			map.addControl(new ml.AttributionControl({ compact: true }), 'top-right');
			map.on('zoom', () => (zoom = map!.getZoom()));
			// The "3D view" buttons inside marker popups.
			el.addEventListener('click', (e) => {
				const id = (e.target as HTMLElement).closest<HTMLElement>('[data-fly]')?.dataset.fly;
				if (id) flyTo(id);
			});
			// Tilting by hand switches 3D on: a tilted flat map is just a stretched map.
			map.on('pitchend', () => {
				if (radar && map!.getPitch() > 10 && prefs.mapTerrain !== 'on') prefs.setMapTerrain(true);
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
				ready = true;
				draw();
				if (radar) refresh();
			});
		});
		return () => {
			cancelled = true;
			loc?.stop();
			loc = null;
			ready = false;
			fetchRun++;
			overlay = null;
			store.clear();
			for (const m of markers) m.remove();
			markers = [];
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
	const legendRamps = [RAMPS.snow, RAMPS.mix, RAMPS.rain];
	const source = $derived(current ? frameSource(current) : '');
	const radarShown = $derived(!!current && current.kind !== 'forecast');
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && infoOpen && (infoOpen = false)} />

<div class="wrap" class:fill={radar} class:dark bind:this={wrap} style:--fill-top="{fillTop}px">
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
				class:active={satellite}
				aria-pressed={satellite}
				onclick={() => prefs.setMapBase(satellite ? 'topo' : 'satellite')}
				title={satellite ? 'Back to the topo map' : 'Satellite imagery'}
				aria-label="Satellite"
			>
				<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
					><path d="M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5" /></svg
				>
			</button>
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
				class:active={pistesOn}
				aria-pressed={pistesOn}
				onclick={() => prefs.setMapPistes(!pistesOn)}
				title={zoom < PISTE_ZOOM
					? 'Ski runs (zoom in to see them)'
					: 'Show or hide ski runs and touring routes'}
				aria-label="Ski runs"
			>
				<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
					><circle cx="15" cy="4.5" r="1.8" /><path
						d="M3 20l18-6M7 18.7l3.5-6 4 1.5-1.5-5-3.5 1.5L8 9M14 8.7l3 2.3"
					/></svg
				>
			</button>
			<button
				class="tool"
				class:active={offlineOpen}
				aria-expanded={offlineOpen}
				onclick={() => {
					offlineOpen = !offlineOpen;
					infoOpen = false;
				}}
				title="Save maps for use with no signal"
				aria-label="Offline maps"
			>
				<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
					><path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19h14" /></svg
				>
			</button>
			<button
				class="tool"
				class:active={infoOpen}
				aria-expanded={infoOpen}
				aria-controls="map-info"
				onclick={() => {
					infoOpen = !infoOpen;
					offlineOpen = false;
				}}
				aria-label="About this map"
			>
				<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
					><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></svg
				>
			</button>
		</div>

		{#if offlineOpen}
			<OfflineMaps
				places={rows
					.filter((r) => r.lat != null && r.lon != null)
					.map((r) => ({ id: r.id, name: r.name, lat: r.lat!, lon: r.lon! }))}
				onclose={() => (offlineOpen = false)}
			/>
		{/if}

		{#if locState === 'locating' || locState === 'denied' || locState === 'unavailable' || offline}
			<p class="note glass" role="status">
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

		{#if infoOpen}
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
						Snow per hour assumes about 10 parts snow to 1 part water. Forecasts beyond a day are
						rougher.
					</p>
				{/if}
				<button class="close" onclick={() => (infoOpen = false)}>Close</button>
			</div>
		{/if}

		{#if on}
			<section class="controls glass" aria-label="Precipitation">
				<div class="modes seg" role="group" aria-label="Show">
					<button aria-pressed={!totalsMode} onclick={() => prefs.setMapMode('timeline')}
						>Radar & forecast</button
					>
					<button aria-pressed={totalsMode} onclick={() => prefs.setMapMode('totals')}
						>Snow total</button
					>
				</div>
				{#if totalsMode}
					{#if total}
						<div class="totals">
							<div class="seg" role="group" aria-label="Window">
								{#each totals as t (t.hours)}
									<button
										aria-pressed={t.hours === total.hours}
										onclick={() => (totalHours = t.hours)}>Next {t.hours} h</button
									>
								{/each}
							</div>
							<span class="span faint">{totalSpan(total)}</span>
						</div>
						<div class="key total-key" aria-label="Snow total, {unit}">
							<span class="name">{unit}</span>
							<span class="ticks-ramp">
								{#each TOTAL as s (s.from)}
									<span class="cell" style:background={s.color}>{totalTick(s.from, units)}</span>
								{/each}
							</span>
						</div>
						<p class="note small-note">
							Canadian HRDPS model, snow at about 10:1; covers Canada and the northern US.
						</p>
					{:else if loadError}
						<p class="note">{loadError}</p>
					{:else}
						<p class="note">Snow totals aren't drawn yet.</p>
					{/if}
				{:else if count && label && current}
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
							{#if nowcastBand}
								<div class="bands" aria-hidden="true">
									<span
										class="nowband"
										title="Nowcast"
										style:left="{nowcastBand.left}%"
										style:width="{nowcastBand.width}%"
									></span>
								</div>
							{/if}
							<div class="ticks" aria-hidden="true">
								{#each ticks as d (d.at)}
									<span class:now={d.now} style:left="{d.at}%">{d.name}</span>
								{/each}
							</div>
						</div>
						<div class="time" aria-live="off">
							<strong class="num">{label.when}</strong>
							<span class:fc={current.kind === 'forecast'} class:nc={current.kind === 'nowcast'}
								>{label.rel}{#if waiting}<i class="spin" aria-label="Loading"></i>{/if}</span
							>
						</div>
					</div>
				{:else if loadError}
					<p class="note">{loadError}</p>
				{:else}
					<p class="note">Loading…</p>
				{/if}
				{#if tooClose}
					<p class="note">Zoom out to see {totalsMode ? 'snow totals' : 'precipitation'}.</p>
				{/if}
				{#if !totalsMode}
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
						{#if radarShown}
							<span class="gaps">{RADAR_GAPS}</span>
						{/if}
					</div>
				{/if}
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

	.tools {
		position: absolute;
		top: 112px;
		left: 10px;
		z-index: 1000;
		display: grid;
		gap: 6px;
	}
	/* Like MapLibre's own buttons, a touch bigger for fingers. */
	.tool {
		width: 32px;
		height: 32px;
		display: grid;
		place-items: center;
		border-radius: 4px;
		border: 0;
		box-shadow: 0 0 0 2px rgb(0 0 0 / 0.1);
		background: #fff;
		color: #333;
		cursor: pointer;
	}
	.tool.three {
		font: 700 0.8rem/1 var(--font-num, sans-serif);
	}
	.tool.active {
		background: var(--accent);
		color: #fff;
	}
	.tool.shown {
		color: var(--accent);
	}
	.tool svg .fill {
		fill: currentColor;
	}
	.note {
		position: absolute;
		top: 10px;
		left: 54px;
		right: 54px;
		max-width: 420px;
		margin: 0 auto;
		z-index: 1001;
		padding: 8px 12px;
		border-radius: 12px;
		font-size: 0.8rem;
		text-align: center;
		color: var(--text);
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
		top: 112px;
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
	.modes {
		justify-self: start;
	}
	.modes button {
		font-size: 0.78rem;
		padding: 3px 10px;
	}
	.totals {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 10px;
	}
	.totals .seg button {
		font-size: 0.78rem;
		padding: 3px 9px;
	}
	.totals .span {
		font-size: 0.75rem;
	}
	.total-key {
		gap: 6px;
	}
	.ticks-ramp {
		display: flex;
		flex: 1;
		min-width: 0;
		border-radius: 4px;
		overflow: hidden;
	}
	.ticks-ramp .cell {
		flex: 1;
		text-align: center;
		font: 600 0.62rem/1.6 var(--font-num, sans-serif);
		color: #1f1b2e;
	}
	.small-note {
		font-size: 0.68rem;
		margin: 0 4px;
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
	.gaps {
		flex-basis: 100%;
		font-size: 0.68rem;
	}
	.time span.nc {
		color: var(--text);
	}
	/* The nowcast's stretch: a thin bar just above the slider, inset like the ticks. */
	.bands {
		position: absolute;
		top: -3px;
		left: 8px;
		right: 8px;
		height: 3px;
		pointer-events: none;
	}
	.nowband {
		position: absolute;
		top: 0;
		height: 100%;
		border-radius: 2px;
		background: color-mix(in srgb, var(--accent) 60%, transparent);
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
	@media (prefers-reduced-motion: reduce) {
		.spin {
			animation-duration: 3s;
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
