<!--
  Every location on a map. Each marker shows the next-5-day snow on the
  Calendar's colour ramp, with a ring in the avalanche danger colour when the
  center's rating is current. Tap a marker for the numbers and a link.
  With `radar`, the map fills the window and becomes the full Map page: one weather
  layer (radar, nowcast and forecast on one timeline, see ../radar.ts, or snow totals),
  one terrain overlay (slope, aspect, elevation bands, sun and shade, or the likely wind
  effect, all computed in the browser, see ../map/terrain/; or the avalanche layers:
  terrain matching today's listed problems and, unless the server has it off, the
  experimental concern index, once this browser has accepted its warning), avalanche danger zones as published, hill shading,
  contours, ski runs and peaks, chosen in the Layers sheet. Tap the map for the terrain there. It's a MapLibre map: tilt and turn it, and
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
	import {
		getAtes,
		getAvalancheZones,
		getConcern,
		getMapPoint,
		getMapWind,
		getReports,
		getSat,
		getStations
	} from '../api';
	import type {
		AtesOut,
		ConcernOut,
		MapStation,
		MapWindOut,
		ObsOut,
		ObsProps,
		PointOut,
		SatOut,
		StationsOut,
		ZoneFeature,
		ZonesOut
	} from '../types.gen';
	import { prefs, type MapWeather } from '../prefs.svelte';
	import { tick, untrack } from 'svelte';
	import { layerLabel, layerSource, WEATHER_WORDS, weatherView } from '../map/weather';
	import { viewport } from '../viewport.svelte';
	import { RAIL_FOLDED_INSET, RAIL_OPEN_INSET, railUi } from '../railui.svelte';
	import {
		frameLabel,
		frameSource,
		loadTimeline,
		PrecipError,
		RADAR_GAPS,
		RAMPS,
		rampTop,
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
		GLACIER_LAYERS,
		halo,
		mapStyle,
		OTM_OPACITY,
		peakColor,
		peakLabel,
		peakText,
		placeLabel,
		PEAK_LAYERS,
		PLACE_LAYERS,
		SKI_DATA,
		ANALYSIS_OPACITY,
		CONCERN_MIN_ZOOM,
		OVERLAY_MIN_ZOOM,
		PRECIP_BEFORE,
		sky,
		SKI_LAYERS,
		SUN_MIN_ZOOM,
		weatherOpacity,
		WIND_MIN_ZOOM
	} from '../map/style';
	import { AnalysisLayer, AreaRunner, viewBounds, type AreaState } from '../map/layers/analysis';
	import { setSnowTiles, snowTilesUrl, TERRAIN_NOTE } from '../map/layers/snowtiles';
	import type { AreaJob } from '../map/terrain/client';
	import type { SunFacts } from '../map/terrain/shade';
	import { sunDay, sunPosition, type Ymd } from '../map/terrain/sun';
	import {
		distanceKm,
		POINT_RANGE_KM,
		WIND_WINDOWS,
		windSource,
		type WindWindow
	} from '../map/windsource';
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
	import AvalancheControls from '../map/AvalancheControls.svelte';
	import ZoneSheet from '../map/ZoneSheet.svelte';
	import ConcernAck from '../map/ConcernAck.svelte';
	import {
		avyHere,
		concernParams,
		concernSetup,
		polygons,
		problemRule,
		todayRatings,
		treelineAt,
		ymd,
		zoneAt,
		zonesGeojson
	} from '../map/avalanche';
	import { addZones, setZones } from '../map/layers/avalanche';
	import { nearestSpot, recentSpec, satViews, type RecentSpec } from '../map/sat';
	import { setRecent, setRecentDates } from '../map/layers/sat';
	import { setSnowLine, SNOWLINE_ZOOM } from '../map/layers/snowline';
	import SatControls from '../map/SatControls.svelte';
	import { matchQuery } from '../map/terrain/client';
	import { concernAt, type ConcernFactors } from '../map/terrain/concern';
	import Measure from '../map/Measure.svelte';
	import StationSheet from '../map/StationSheet.svelte';
	import ReportSheet from '../map/ReportSheet.svelte';
	import { plainLine, setMeasure } from '../map/layers/measure';
	import {
		lineBounds,
		parseGpx,
		sampleLine,
		segmentsGeojson,
		type LngLat,
		type Sample
	} from '../map/measure';
	import { atesGeojson, reportsGeojson, stationsGeojson } from '../map/features';
	import { setAtes, setReports, setStations, TAP_LAYERS } from '../map/layers/features';
	import { HERE_LAYERS, hereItems, skiLines, type HereItem, type SkiLines } from '../map/here';

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
	/** Recent satellite: daily VIIRS, and Sentinel-2 scenes near the locations (../map/sat.ts). */
	const recent = $derived(radar && prefs.mapBase === 'recent');
	/** Either kind of imagery: place names and contours go over it. */
	const imagery = $derived(satellite || recent);
	const runsOn = $derived(radar && prefs.mapFeatures.has('runs'));
	const peaksOn = $derived(!radar || prefs.mapFeatures.has('peaks'));
	const placesOn = $derived(radar && prefs.mapFeatures.has('places'));
	const glaciersOn = $derived(radar && prefs.mapFeatures.has('glaciers'));
	const stationsOn = $derived(radar && prefs.mapFeatures.has('stations'));
	const reportsOn = $derived(radar && prefs.mapFeatures.has('obs'));
	/** Contours show on imagery: the topo maps draw their own. */
	const contoursOn = $derived(radar && prefs.mapFeatures.has('contours') && imagery && !offline);
	/** The concern index's settings; null until loaded, or when the server has it off. */
	let concernCfg = $state.raw<ConcernOut | null>(null);
	/** The concern index is chosen but its warning hasn't been accepted on this device. */
	const askAck = $derived(
		radar && prefs.mapOverlay === 'concern' && !!concernCfg && !prefs.concernAck
	);
	const overlayMode = $derived(
		!radar || (prefs.mapOverlay === 'concern' && (!concernCfg || !prefs.concernAck))
			? 'none'
			: prefs.mapOverlay
	);
	const zonesOn = $derived(radar && prefs.mapFeatures.has('zones'));
	const avyOverlay = $derived(overlayMode === 'problems' || overlayMode === 'concern');
	// The precipitation pictures are ~1.4 km a pixel: they fade as the map zooms past
	// that and are gone up close, where one pixel would fill the screen.
	const weather = $derived<MapWeather>(radar ? prefs.mapWeather : 'off');
	/** Smooth fields (totals, snow level, wind, snow on the ground) stay on further in. */
	const tooClose = $derived(zoom >= (weather === 'radar' || weather === 'clouds' ? 13 : 15));

	function togglePanel(p: 'info' | 'offline' | 'layers') {
		panel = panel === p ? 'none' : p;
		closeSheets();
	}
	/** The sheets a tap on the map opens: a zone's bulletin, a station, a field report. */
	function closeSheets() {
		zoneOpen = null;
		stationOpen = null;
		reportOpen = null;
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
		// No haze over recent satellite imagery in 3D: nothing should dim it.
		const s = sky(d, recent);
		if (s) map.setSky(s);
	});

	$effect(() => {
		// Offline, only OpenTopoMap is saved (Esri's terms don't allow storing its tiles),
		// so it shows at every zoom and satellite (of either kind) waits for a connection.
		const off = offline;
		const sat = satellite && !off;
		const img = imagery && !off;
		if (!ready || !map) return;
		map.setLayoutProperty('esri', 'visibility', img || off ? 'none' : 'visible');
		map.setLayoutProperty('otm', 'visibility', img ? 'none' : 'visible');
		map.setLayerZoomRange('otm', off ? 0 : DETAIL_ZOOM - 0.5, 24);
		map.setPaintProperty('otm', 'raster-opacity', off ? 1 : OTM_OPACITY);
		map.setLayoutProperty('sat', 'visibility', sat ? 'visible' : 'none');
		map.setLayoutProperty('satlabels', 'visibility', img ? 'visible' : 'none');
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
		const places = placesOn;
		const glaciers = glaciersOn;
		if (!ready || !map) return;
		const show = (ids: string[], on: boolean) => {
			for (const id of ids)
				if (map!.getLayer(id)) map!.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
		};
		show(SKI_LAYERS, runs);
		show(PEAK_LAYERS, peaks);
		show(PLACE_LAYERS, places);
		show(GLACIER_LAYERS, glaciers);
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
		if (map.getLayer('place-labels')) {
			map.setLayoutProperty('place-labels', 'text-field', placeLabel(u));
			map.setPaintProperty('place-labels', 'text-halo-color', halo(d));
			map.setPaintProperty('place-labels', 'text-color', peakText(d));
		}
	});

	// ---- Terrain layers ------------------------------------------------------------
	$effect(() => {
		const o = overlayMode;
		const q = matchQ;
		if (!ready || !map || !radar) return;
		// The worker needs the zone's outline before it draws tiles clipped to it.
		if (q && centreZone) terrainClient()?.setZone(centreZone.id, polygons(centreZone.geometry));
		setOverlay(map, o, q);
	});
	$effect(() => {
		// No hill shading over recent satellite (the Sun & shade layer still lights the
		// hills, since that's what it shows).
		const s = recent ? 'off' : prefs.mapShade;
		const d = dark;
		const b = prefs.mapBase === 'topo' || !radar ? 'topo' : prefs.mapBase;
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
	const concernOn = $derived(overlayMode === 'concern');
	const areaTooFar = $derived(
		(sunOn && zoom < SUN_MIN_ZOOM) ||
			(windOn && zoom < WIND_MIN_ZOOM) ||
			(concernOn && zoom < CONCERN_MIN_ZOOM)
	);
	/** Hill shading lit from where the sun is, while the shade is showing. */
	const sunLight = $derived(
		sunOn && sunMode === 'shade' && sunPos && sunPos.altitude > 0 && !areaTooFar ? sunPos : null
	);
	/** The map's own forecast at the centre: the wind-effect layer's wind away from locations. */
	let centrePoint = $state.raw<PointOut | null>(null);
	let pointTried = $state(false);
	$effect(() => {
		const c = centre;
		if (!windOn || !windLoaded || areaTooFar) return;
		if (untrack(() => windSource(windData, c.lat, c.lon, 'next24'))) return;
		const have = untrack(() => centrePoint);
		if (have && distanceKm(have.lat, have.lon, c.lat, c.lon) < POINT_RANGE_KM / 2) return;
		pointTried = false;
		let gone = false;
		getMapPoint(c.lat, c.lon)
			.then((p) => !gone && (centrePoint = p))
			.catch((e) => console.error('point', e))
			.finally(() => !gone && (pointTried = true));
		return () => (gone = true);
	});
	const wind = $derived(windSource(windData, centre.lat, centre.lon, windWindow, centrePoint));

	// The locations' wind, fetched when the layer is first switched on.
	$effect(() => {
		if (!(windOn || concernOn) || windLoaded) return;
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
		} else if (mode === 'concern' && !areaTooFar && concernCfg && centreZone) {
			const setup = concern;
			if (setup?.inputs)
				job = {
					type: 'concern',
					inputs: $state.snapshot(setup.inputs),
					params: concernParams(concernCfg),
					windSectors: setup.windSectors,
					windScale: setup.windScale,
					sunDate: setup.inputs.sun ? ymd(centreZone.properties.today) : null,
					zone: polygons(centreZone.geometry)
				};
			opacity = ANALYSIS_OPACITY.concern;
		}
		if (!ready || !map || !runner) return;
		if (job) runner.request(job, viewBounds(map), AREA_PX, opacity);
		else runner.request(null);
	});

	// ---- Recent satellite ----------------------------------------------------------
	let satData = $state.raw<SatOut | null>(null);
	let satState = $state<'idle' | 'loading' | 'ready' | 'failed'>('idle');
	/** Which of the nearest location's views is shown (0: stitched, when there is one). */
	let sceneIndex = $state(0);
	async function loadSat() {
		if (satState === 'loading') return;
		satState = 'loading';
		try {
			satData = await getSat();
			satState = 'ready';
		} catch (e) {
			console.error('recent satellite', e);
			satState = satData ? 'ready' : 'failed';
		}
	}
	// Fetched when the base is first switched to it; new scenes arrive every few hours.
	$effect(() => {
		if (recent && !offline && satState === 'idle') void loadSat();
	});
	$effect(() => {
		if (!recent) return;
		const id = setInterval(() => satState !== 'loading' && void loadSat(), 30 * 60 * 1000);
		return () => clearInterval(id);
	});
	const satSpot = $derived(nearestSpot(satData, centre.lat, centre.lon)?.spot ?? null);
	// Another location's scenes: start from its newest.
	let sceneSpot = '';
	$effect(() => {
		const id = satSpot?.id ?? '';
		if (id !== sceneSpot) {
			sceneSpot = id;
			sceneIndex = 0;
		}
	});
	/** What the Sentinel-2 tier shows: stitched first, then whole scenes. */
	const satView = $derived.by(() => {
		const views = satViews(satSpot);
		return views.length ? views[Math.min(sceneIndex, views.length - 1)] : null;
	});
	const NO_RECENT: RecentSpec = { viirs: null, view: null, dates: null };
	$effect(() => {
		const spec =
			recent && !offline ? recentSpec(satData, satSpot, satView, prefs.satBands) : NO_RECENT;
		if (!ready || !map) return;
		// Over the other bases, under the hill shading and everything else.
		setRecent(map, spec, 'shade');
		setRecentDates(map, spec.dates);
	});

	// ---- Avalanche: zones as published, problems as terrain, the concern index -----------
	let zonesData = $state.raw<ZonesOut | null>(null);
	let zonesState = $state<'idle' | 'loading' | 'ready' | 'failed'>('idle');
	/** The zone whose bulletin is open. */
	let zoneOpen = $state.raw<ZoneFeature | null>(null);
	let problemPick = $state<number | 'all'>('all');
	let problemSlope = $state(30);

	async function loadZones() {
		if (zonesState === 'loading') return;
		const first = !zonesData;
		zonesState = 'loading';
		try {
			const d = await getAvalancheZones();
			if (first) problemSlope = d.problem_slope_deg ?? 30;
			zonesData = d;
			zonesState = 'ready';
		} catch (e) {
			console.error('avalanche zones', e);
			// A refresh that fails keeps what's shown (the API applied expiry when it was sent).
			zonesState = zonesData ? 'ready' : 'failed';
		}
	}
	// Fetched the first time something needs them; refreshed every 5 minutes after that.
	$effect(() => {
		if ((zonesOn || avyOverlay || probe) && zonesState === 'idle') void loadZones();
	});
	$effect(() => {
		if (!radar) return;
		void getConcern()
			.then((c) => (concernCfg = c))
			.catch((e) => console.error('concern', e));
	});

	const centreZone = $derived(
		zonesData ? zoneAt(zonesData.features, centre.lat, centre.lon) : null
	);
	const centreTreeline = $derived(
		zonesData ? treelineAt(zonesData, centreZone, centre.lat, centre.lon) : null
	);
	/** The problems layer's terrain:// query, or null when there's nothing to match. */
	const matchQ = $derived.by(() => {
		if (overlayMode !== 'problems' || !centreZone || !centreTreeline) return null;
		const v = centreZone.properties.view;
		const probs = todayRatings(v, centreZone.properties.today) ? (v.doc?.problems ?? []) : [];
		if (!probs.length) return null;
		const chosen =
			typeof problemPick === 'number' && probs[problemPick] ? [probs[problemPick]] : probs;
		return matchQuery(
			{ slopeMin: problemSlope, rules: chosen.map((p) => problemRule(p, centreTreeline.band)) },
			centreZone.id
		);
	});
	/** What the concern index uses for the zone in the middle of the map. */
	const concern = $derived(
		concernOn && concernCfg && centreTreeline
			? concernSetup(
					centreZone,
					centreTreeline,
					windSource(windData, centre.lat, centre.lon, 'past48'),
					concernCfg.wind_snow_cm
				)
			: null
	);

	$effect(() => {
		const d = zonesData;
		if (!ready || !map || !d) return;
		addZones(
			map,
			zonesGeojson(d.features),
			map.getLayer('overlay') ? 'overlay' : PRECIP_BEFORE,
			PRECIP_BEFORE
		);
	});
	$effect(() => {
		const d = zonesData;
		const on = zonesOn;
		const focus = avyOverlay ? (centreZone?.id ?? null) : null;
		const dk = dark;
		if (ready && map && d) setZones(map, on, focus, dk);
	});

	// ---- Snow stations, field reports and ATES ratings -----------------------------------
	let stationsData = $state.raw<StationsOut | null>(null);
	let reportsData = $state.raw<ObsOut | null>(null);
	let atesData = $state.raw<AtesOut | null>(null);
	/** Fetched once each, when first needed; null data after a load means none on the server. */
	let loaded = $state({ stations: false, reports: false, ates: false });
	let stationOpen = $state.raw<MapStation | null>(null);
	let reportOpen = $state.raw<ObsProps | null>(null);
	const atesOn = $derived(radar && prefs.mapFeatures.has('ates') && !!atesData);

	async function loadFeature(which: 'stations' | 'reports' | 'ates') {
		try {
			if (which === 'stations') stationsData = await getStations();
			else if (which === 'reports') reportsData = await getReports();
			else atesData = await getAtes();
		} catch (e) {
			console.error(which, e);
		} finally {
			loaded = { ...loaded, [which]: true };
		}
	}
	$effect(() => {
		if (offline) return;
		if (stationsOn && !untrack(() => loaded.stations)) void loadFeature('stations');
		if (reportsOn && !untrack(() => loaded.reports)) void loadFeature('reports');
		// Whether the server has ATES files is known once the Layers sheet has been opened.
		if (
			radar &&
			(panel === 'layers' || prefs.mapFeatures.has('ates')) &&
			!untrack(() => loaded.ates)
		)
			void loadFeature('ates');
	});
	// Stations report hourly; new field reports come in through the day.
	$effect(() => {
		if (!radar) return;
		const id = setInterval(
			() => {
				if (stationsOn) void loadFeature('stations');
				if (reportsOn) void loadFeature('reports');
			},
			30 * 60 * 1000
		);
		return () => clearInterval(id);
	});
	$effect(() => {
		const d = stationsData;
		const on = stationsOn;
		const u = units;
		const h = halo(dark);
		if (ready && map && (d || map.getSource('stations')))
			setStations(map, d ? stationsGeojson(d, u) : null, on, h);
	});
	$effect(() => {
		const d = reportsData;
		const on = reportsOn;
		if (ready && map && (d || map.getSource('reports')))
			setReports(map, d ? reportsGeojson(d) : null, on);
	});
	$effect(() => {
		const d = atesData;
		const on = atesOn;
		// Under the place names, runs and the weather.
		if (ready && map && (d || map.getSource('ates')))
			setAtes(map, d ? atesGeojson(d) : null, on, PRECIP_BEFORE);
	});

	// ---- Measure: a line tapped out, a run or route, or a GPX track ----------------------
	let measuring = $state(false);
	/** Taps on the map add points (rather than a run or track being shown). */
	let measureEdit = $state(false);
	let measurePts = $state.raw<LngLat[]>([]);
	let measureTitle = $state('Measure');
	let measureNote = $state('');
	let measureSamples = $state.raw<Sample[] | null>(null);
	let measureState = $state<'idle' | 'loading' | 'ready' | 'failed'>('idle');
	let measureError = $state<string | null>(null);
	let gpxError = $state<string | null>(null);
	let measureHover = $state<number | null>(null);
	/** Every run's and route's whole line, fetched the first time one is profiled. */
	let skiIndex: SkiLines | null = null;

	// The terrain under the line, again whenever it changes (the last request is called off).
	$effect(() => {
		const pts = measurePts;
		const on = measuring;
		measureSamples = null;
		measureHover = null;
		measureError = null;
		if (!on || pts.length < 2) {
			measureState = 'idle';
			return;
		}
		const c = terrainClient();
		if (!c) {
			measureState = 'failed';
			measureError = 'Measuring needs a newer browser.';
			return;
		}
		const ctl = new AbortController();
		measureState = 'loading';
		sampleLine(pts, (q, z, sig) => c.profile(q, z, sig), ctl.signal).then(
			(got) => {
				if (ctl.signal.aborted) return;
				measureSamples = got;
				measureState = 'ready';
			},
			(e) => {
				if (ctl.signal.aborted) return;
				measureState = 'failed';
				measureError = offline
					? 'No saved terrain along this line. Save the area for offline use first.'
					: `Couldn’t measure the terrain along this line (${e instanceof Error ? e.message : e}).`;
			}
		);
		return () => ctl.abort();
	});
	$effect(() => {
		const on = measuring;
		const pts = measurePts;
		const s = measureSamples;
		const hv = measureHover;
		const edit = measureEdit;
		if (!ready || !map) return;
		if (!on) return setMeasure(map, null);
		setMeasure(map, {
			line: s ? segmentsGeojson(s) : plainLine(pts),
			points: edit ? pts : [],
			hover: hv != null && s?.[hv] ? [s[hv].lon, s[hv].lat] : null
		});
	});

	function startMeasure() {
		panel = 'none';
		closeSheets();
		closeInspector();
		measuring = true;
		measureEdit = true;
		measurePts = [];
		measureTitle = 'Measure';
		measureNote = '';
		gpxError = null;
	}
	function stopMeasure() {
		measuring = false;
		measureEdit = false;
		measurePts = [];
		gpxError = null;
	}
	/** Show a whole line (a run, a route, a track) with its numbers and profile. */
	function showLine(title: string, note: string, pts: LngLat[], fit: boolean) {
		measuring = true;
		measureEdit = false;
		measureTitle = title;
		measureNote = note;
		measurePts = pts;
		gpxError = null;
		if (fit && map) {
			const [w, s_, e, n] = lineBounds(pts);
			// Once the panel is on screen, so the track lands in the space above it (the
			// map's padding; this padding is on top of that).
			void tick().then(() => {
				if (!map) return;
				applyPadding(false);
				map.fitBounds(
					[
						[w, s_],
						[e, n]
					],
					{ padding: { top: 60, bottom: 40, left: 50, right: 50 }, maxZoom: 15 }
				);
			});
		}
	}
	async function openGpx(file: File) {
		try {
			if (file.size > 30_000_000) throw new Error('This file is too big for a GPX track.');
			const t = parseGpx(await file.text());
			closeInspector();
			showLine(
				t.name || file.name.replace(/\.gpx$/i, ''),
				'GPX · read on this device',
				t.points,
				true
			);
		} catch (e) {
			measuring = true;
			gpxError = e instanceof Error ? e.message : String(e);
		}
	}
	/** The Inspector's Profile button on a run or route. */
	async function profileRun(item: HereItem) {
		let line = item.line;
		if (item.osm) {
			try {
				if (!skiIndex) {
					const r = await fetch(SKI_DATA);
					if (r.ok) skiIndex = skiLines(await r.json());
				}
				line = skiIndex?.get(item.osm) ?? line;
			} catch (e) {
				console.error('ski map', e);
			}
		}
		if (!line || line.length < 2) return;
		// The whole run turned out to be an outline (the tap only saw part of it).
		const [a, b] = [line[0], line[line.length - 1]];
		if (item.kind !== 'Route' && line.length > 3 && a[0] === b[0] && a[1] === b[1]) {
			showLine(item.name, `${item.kind} · OpenStreetMap`, [], false);
			gpxError = 'This run is mapped as its outline, so it has no profile.';
			return;
		}
		showLine(item.name, `${item.kind} · OpenStreetMap`, line, false);
	}

	// ---- Inspector: tap the map for the terrain there --------------------------------
	let probe = $state<{ lat: number; lon: number } | null>(null);
	let facts = $state<PointFacts | null>(null);
	let factsError = $state<string | null>(null);
	let probeSun = $state<SunFacts | null>(null);
	let probeWind = $state<{ value: number; window: string } | null>(null);
	/** What the map's weather says at the tapped spot (/api/map/point). */
	let probePoint = $state.raw<PointOut | null>(null);
	let probePointState = $state<'loading' | 'ready' | 'failed'>('loading');
	let probeMarker: Marker | null = null;
	let probeToken = 0;
	/** Map features where the map was tapped: a run, a hut, a glacier, an ATES rating. */
	let probeHere = $state.raw<HereItem[]>([]);

	const probeZone = $derived(
		probe && zonesData ? zoneAt(zonesData.features, probe.lat, probe.lon) : null
	);
	const probeAvy = $derived(
		probe && facts && !facts.sea && zonesData && probeZone
			? avyHere(zonesData, probeZone, probe.lat, probe.lon, facts.elevation)
			: null
	);
	let probeConcern = $state<ConcernFactors | null>(null);
	// The concern index's factors at the tapped spot, with its own zone, wind and sun.
	$effect(() => {
		const p = probe;
		const f = facts;
		probeConcern = null;
		const c = terrainClient();
		if (!p || !f || f.sea || !concernOn || !concernCfg || !zonesData || !probeZone || !c) return;
		const setup = concernSetup(
			probeZone,
			treelineAt(zonesData, probeZone, p.lat, p.lon),
			windSource(windData, p.lat, p.lon, 'past48'),
			concernCfg.wind_snow_cm
		);
		const inputs = setup.inputs;
		if (!inputs) return;
		const params = concernParams(concernCfg);
		let gone = false;
		const sectors = setup.windSectors;
		Promise.all([
			inputs.wind && sectors ? c.windPoint(p.lat, p.lon, sectors) : Promise.resolve(null),
			inputs.sun ? c.sunPoint(p.lat, p.lon, ymd(probeZone.properties.today)) : Promise.resolve(null)
		]).then(
			([w, s]) => {
				if (gone) return;
				probeConcern = concernAt(
					{
						elev: f.elevation,
						slope: f.slope,
						aspect: f.aspect,
						wind: w == null ? null : w * setup.windScale,
						sunHours: s ? s.hours : null
					},
					inputs,
					params
				);
			},
			() => {}
		);
		return () => (gone = true);
	});

	async function inspect(lat: number, lon: number) {
		const c = terrainClient();
		if (!c || !map || !ml) return;
		const token = ++probeToken;
		probe = { lat, lon };
		facts = null;
		factsError = null;
		probeSun = null;
		probeWind = null;
		probePoint = null;
		probePointState = 'loading';
		// The weather there comes from the server, the terrain from this device: each joins
		// the sheet when it's ready.
		const pointP = offline ? Promise.reject(new Error('offline')) : getMapPoint(lat, lon);
		pointP.then(
			(p) => {
				if (token !== probeToken) return;
				probePoint = p;
				probePointState = 'ready';
			},
			() => token === probeToken && (probePointState = 'failed')
		);
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
			// The nearest location's wind, else the map's forecast at the spot itself.
			const w =
				windSource(windData, lat, lon, windWindow) ??
				(windOn
					? await pointP.then(
							(p) => windSource(windData, lat, lon, windWindow, p),
							() => null
						)
					: null);
			if (token !== probeToken) return;
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
		probePoint = null;
		probeHere = [];
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

	// The full map fills the window. On phones and tablets it starts below the header (and
	// any banner) and the tab bar floats over it; on desktop it fills the whole window and
	// the navigation rail floats over its left side (open, or folded to a button).
	let fillTop = $state(0);
	$effect(() => {
		if (!radar || !wrap) return;
		const desktop = viewport.desktop;
		const main = wrap.closest('main');
		// Whole pixels: a map placed at a fractional offset blends every tile edge,
		// which draws a faint grid.
		const measure = () => {
			fillTop = desktop
				? 0
				: Math.round((main ?? wrap!).getBoundingClientRect().top + window.scrollY);
		};
		measure();
		window.addEventListener('resize', measure);
		return () => window.removeEventListener('resize', measure);
	});
	/** How far the rail (or its folded button) reaches over the map from the left. */
	const inset = $derived(
		radar && viewport.desktop ? (railUi.folded ? RAIL_FOLDED_INSET : RAIL_OPEN_INSET) : 0
	);

	// ---- The map's centre in the free space -------------------------------------------
	// Like a phone's maps app with its sheet up or down: the map's padding is the part the
	// open rail and the controls at the foot cover, so its centre (and every fit, fly-to
	// and "the middle of the map" this page uses) sits in the space left over, and moves
	// smoothly when a panel opens, closes or the rail folds.
	let dock = $state<HTMLDivElement>();
	let padKey = '';
	function mapPadding() {
		if (!map || !wrap) return null;
		const box = wrap.getBoundingClientRect();
		let bottom = 0;
		if (dock && dock.childElementCount) {
			const top = Math.min(
				...[...dock.children].map((c) => c.getBoundingClientRect().top).filter((t) => t > 0)
			);
			if (Number.isFinite(top)) bottom = Math.max(0, Math.round(box.bottom - top));
		}
		// The folded button is small, like the map's own buttons: the map doesn't move for it.
		const left = radar && viewport.desktop && !railUi.folded ? RAIL_OPEN_INSET : 0;
		// Never more than half the map either way, so the centre stays on screen.
		return {
			top: 0,
			right: 0,
			left: Math.min(left, Math.round(box.width / 2)),
			bottom: Math.min(bottom, Math.round(box.height / 2))
		};
	}
	function applyPadding(animate: boolean) {
		const pad = mapPadding();
		if (!pad || !map) return;
		const key = `${pad.left}/${pad.bottom}`;
		if (key === padKey) return;
		const old = padKey.split('/').map(Number);
		padKey = key;
		// Small changes (a control's height wobbling) aren't worth moving the map for.
		if (old.length === 2 && Math.abs(old[0] - pad.left) + Math.abs(old[1] - pad.bottom) < 12) {
			map.setPadding(pad);
			return;
		}
		if (animate && !map.isMoving()) map.easeTo({ padding: pad, duration: 450 });
		else map.setPadding(pad);
	}
	$effect(() => {
		void inset;
		const d = dock;
		if (!ready || !radar) return;
		applyPadding(true);
		if (!d || typeof ResizeObserver === 'undefined') return;
		let t: ReturnType<typeof setTimeout>;
		const ro = new ResizeObserver(() => {
			clearTimeout(t);
			t = setTimeout(() => applyPadding(true), 60);
		});
		ro.observe(d);
		for (const c of d.children) ro.observe(c);
		// Panels come and go inside the dock.
		const mo = new MutationObserver(() => {
			for (const c of d.children) ro.observe(c);
			clearTimeout(t);
			t = setTimeout(() => applyPadding(true), 60);
		});
		mo.observe(d, { childList: true });
		const onResize = () => applyPadding(false);
		window.addEventListener('resize', onResize);
		return () => {
			clearTimeout(t);
			ro.disconnect();
			mo.disconnect();
			window.removeEventListener('resize', onResize);
		};
	});

	// ---- Weather layer ----------------------------------------------------------------
	// The server draws every picture; here we download them once and swap them.
	const on = $derived(weather !== 'off');
	let timeline = $state<Timeline | null>(null);
	/** Why the weather isn't showing, in words; null when it is. */
	let loadError = $state<string | null>(null);
	let frame = $state(0);
	// Loops play by themselves, unless the device asks for less motion.
	let playing = $state(
		typeof matchMedia === 'undefined' || !matchMedia('(prefers-reduced-motion: reduce)').matches
	);
	let now = $state(Date.now());
	/** The picture on screen (file name), which lags the wanted one while it decodes. */
	let shown = $state<string | null>(null);
	/** Frames downloaded so far. */
	let ready_ = $state<Set<string>>(new Set());

	/** What the chosen layer shows: a loop of frames, or pictures picked by window. */
	const view = $derived(weatherView(timeline, weather, prefs.mapWind));
	const looping = $derived(view.mode === 'loop');
	const frames = $derived(view.frames);
	const count = $derived(frames.length);
	const current = $derived<Frame | undefined>(
		looping ? frames[Math.min(frame, count - 1)] : undefined
	);
	const label = $derived(
		current ? (weather === 'radar' ? frameLabel(current, now) : layerLabel(current, now)) : null
	);
	/** Each window-type layer's chosen window, in hours. */
	let picked = $state<Record<string, number>>({ totals: 24, snowfall: 24, depth: 0 });
	const pick = $derived(
		view.mode === 'pick'
			? (view.picks.find((p) => p.id === picked[weather]) ??
					view.picks[Math.min(1, view.picks.length - 1)])
			: undefined
	);
	const waiting = $derived(
		(!!current && shown !== current.file) || (!!pick && shown !== pick.file)
	);

	const store = new FrameStore();
	let overlay: PrecipLayer | null = null;
	$effect(() => {
		const o = weatherOpacity(weather);
		if (ready && map?.getLayer(PrecipLayer.ID))
			map.setPaintProperty(PrecipLayer.ID, 'raster-opacity', o);
	});

	/** Put the wanted picture on screen; the old one stays until the new one is decoded. */
	let showToken = 0;
	async function show() {
		if (!map || !timeline) return;
		const want = pick ?? current;
		if (!on || !want) {
			++showToken;
			overlay?.draw(null, null);
			shown = null;
			return;
		}
		const token = ++showToken;
		const bmp = await store.bitmap(want);
		if (token !== showToken || !overlay) return;
		overlay.draw(want.file, bmp);
		shown = want.file;
		// Have the next one decoded before it's asked for.
		const next = looping ? frames[(frame + 1) % count] : undefined;
		if (next) void store.bitmap(next);
	}

	/**
	 * Download the loop's frames, nearest to the one on screen first. Radar frames beyond
	 * ~48 h wait until the slider reaches them or the page has sat idle 5 seconds, so the
	 * first paint stays a couple of MB.
	 */
	let fetchRun = 0;
	let extendedWanted = $state(false);
	let idleTimer: ReturnType<typeof setTimeout> | undefined;
	async function fetchAll() {
		const run = ++fetchRun;
		if (!timeline || !looping) return;
		const from = view.extendedFrom;
		const list = frames;
		const order = list
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
		const from = view.extendedFrom;
		if (from >= 0 && frame >= from && looping) extendedWanted = true;
	});
	$effect(() => {
		if (extendedWanted && ready) void untrack(fetchAll);
	});
	$effect(() => () => clearTimeout(idleTimer));
	// Another loop (or a new index): note what's already downloaded, fetch the rest.
	$effect(() => {
		const list = frames;
		if (!ready) return;
		ready_ = new Set(list.filter((f) => store.has(f)).map((f) => f.file));
		void untrack(fetchAll);
	});
	// Another layer: start it at "now" (or its first frame).
	let lastLayer = '';
	$effect(() => {
		const key = `${weather}|${prefs.mapWind}`;
		if (key === lastLayer) return;
		lastLayer = key;
		frame = Math.max(
			0,
			untrack(() => view.now)
		);
	});

	async function refresh() {
		try {
			const before = current?.t;
			const atNow = !timeline || frame === Math.max(0, view.now);
			const tl = await loadTimeline();
			loadError = null;
			// The pictures' box only changes when locations do.
			const sameBox = timeline && JSON.stringify(timeline.bounds) === JSON.stringify(tl.bounds);
			const next = weatherView(tl, weather, prefs.mapWind);
			timeline = tl;
			store.keepOnly([...tl.frames, ...tl.totals, ...Object.values(tl.layers).flat()]);
			// Keep the viewer's place if that time still exists; otherwise go to "now".
			const same = next.frames.findIndex((f) => f.t === before);
			frame = atNow || same < 0 ? Math.max(0, next.now) : same;
			if (map && (!overlay || !sameBox)) {
				overlay?.remove();
				// Over the base map, under the satellite labels and the ski runs.
				overlay = new PrecipLayer(
					map,
					tl.bounds,
					tl.width,
					tl.height,
					weatherOpacity(weather),
					PRECIP_BEFORE
				);
			}
			void show();
		} catch (e) {
			loadError =
				e instanceof PrecipError
					? e.message
					: `The weather couldn't be shown (${e instanceof Error ? e.message : e}).`;
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
		void current;
		void pick;
		if (ready) void show();
	});

	// Play: step when the next frame is on hand (or after a short wait), quicker through
	// observations, and hold a moment on "now" and on the last frame.
	$effect(() => {
		if (!ready || !playing || !looping || count < 2) return;
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
				frame = Math.max(0, view.now);
				return;
			}
			frame = next;
			if (next === count - 1) hold = 4;
			else if (next === view.now) hold = 3;
		};
		id = setTimeout(tick, 600);
		return () => clearTimeout(id);
	});

	// ---- Terrain-adjusted snow totals (Snow total, zoomed in) ----------------------------
	/** The picked total's terrain-adjusted tiles, when the server has drawn them. */
	const snowTiles = $derived(
		weather === 'totals' && on && !offline && pick?.tiles ? pick.tiles : null
	);
	/** They're what's on screen (zoomed in far enough). */
	const adjusted = $derived(!!snowTilesUrl(snowTiles ? pick : undefined, zoom));
	$effect(() => {
		const tiles = snowTiles;
		const tl = timeline;
		if (!ready || !map || !tl) return;
		setSnowTiles(map, tiles, {
			bounds: tl.bounds,
			opacity: weatherOpacity('totals'),
			beforeId: PRECIP_BEFORE,
			pictureId: PrecipLayer.ID
		});
	});

	// ---- The rain/snow line draped on the terrain (Snow level, zoomed in) --------------
	/** The map's forecast at the centre, for the snow level the drape uses. */
	let levelPoint = $state.raw<PointOut | null>(null);
	const lineOn = $derived(weather === 'snowlevel' && zoom >= SNOWLINE_ZOOM - 0.5 && !offline);
	$effect(() => {
		const c = centre;
		if (!lineOn) return;
		const have = untrack(() => levelPoint);
		if (have && distanceKm(have.lat, have.lon, c.lat, c.lon) < 3) return;
		let gone = false;
		getMapPoint(c.lat, c.lon)
			.then((p) => !gone && (levelPoint = p))
			.catch((e) => console.error('point', e));
		return () => (gone = true);
	});
	/** The snow level at the map's centre for the frame on the slider. */
	const centreLevel = $derived.by(() => {
		if (!lineOn || !levelPoint || !current) return null;
		const t = current.t;
		return levelPoint.snow_level.find((x) => x.t === t)?.value ?? null;
	});
	$effect(() => {
		const level = centreLevel;
		if (ready && map && radar) setSnowLine(map, level, PrecipLayer.ID);
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
			setInterval(() => zonesState === 'ready' && void loadZones(), 5 * 60 * 1000),
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
					places: prefs.mapFeatures.has('places'),
					glaciers: prefs.mapFeatures.has('glaciers'),
					contours: contoursOn,
					shade: prefs.mapShade,
					overlay: overlayMode,
					worker: terrain.worker,
					contourTiles: ctiles
				}),
				center: [-120.8, 47.3],
				zoom: radar ? 6 : 5,
				pitch: 0,
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
				if (!radar) return;
				if (popups.some((p) => p.isOpen())) {
					for (const p of popups) p.remove();
					return;
				}
				if (panel !== 'none' || zoneOpen || stationOpen || reportOpen) {
					panel = 'none';
					closeSheets();
					return;
				}
				if (measuring && measureEdit) {
					measurePts = [...measurePts, [e.lngLat.lng, e.lngLat.lat]];
					return;
				}
				const near = (px: number): [[number, number], [number, number]] => [
					[e.point.x - px, e.point.y - px],
					[e.point.x + px, e.point.y + px]
				];
				// A station or a field report opens its own sheet.
				const tapLayers = TAP_LAYERS.filter((id) => map!.getLayer(id));
				const tapped = tapLayers.length
					? map!.queryRenderedFeatures(near(8), { layers: tapLayers })[0]
					: undefined;
				const i = Number(tapped?.properties?.i);
				if (tapped?.layer.id === 'stations' && stationsData?.stations[i]) {
					closeInspector();
					stationOpen = stationsData.stations[i];
					return;
				}
				if (tapped?.layer.id === 'reports' && reportsData?.features[i]) {
					closeInspector();
					reportOpen = reportsData.features[i].properties;
					return;
				}
				if (!analysis) {
					// No terrain worker (old browsers): a tap on a zone opens its bulletin.
					const z =
						zonesOn && zonesData ? zoneAt(zonesData.features, e.lngLat.lat, e.lngLat.lng) : null;
					if (z) zoneOpen = z;
					return;
				}
				void inspect(e.lngLat.lat, e.lngLat.lng);
				const hereLayers = HERE_LAYERS.filter((id) => map!.getLayer(id));
				probeHere = hereLayers.length
					? hereItems(
							map!.queryRenderedFeatures(near(5), { layers: hereLayers }).map((f) => ({
								layer: f.layer.id,
								properties: f.properties ?? {},
								geometry: f.geometry as { type: string; coordinates?: unknown }
							})),
							units,
							skiIndex
						)
					: [];
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
				// The free space first, so framing the locations lands beside the rail.
				if (radar) applyPadding(false);
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
	/** Washington State ([west, south], [east, north]): where the full map opens. */
	const HOME_BOUNDS: [[number, number], [number, number]] = [
		[-124.8, 45.5],
		[-116.9, 49.05]
	];
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
		// The full map opens flat over Washington, home for this site, whatever else is saved.
		if (radar && !fitted) {
			fitted = true;
			map.fitBounds(HOME_BOUNDS, { padding: 30, animate: false });
		}
		// The small overview map frames the locations once; after that the view is the viewer's.
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
	const source = $derived(
		weather === 'radar'
			? current
				? frameSource(current)
				: ''
			: looping
				? layerSource(weather, prefs.mapWind, current)
				: (pick?.sources ?? '')
	);
	const radarShown = $derived(!!current && current.kind !== 'forecast');
</script>

<svelte:window
	onkeydown={(e) =>
		e.key === 'Escape' &&
		(askAck
			? prefs.setMapOverlay('none')
			: zoneOpen || stationOpen || reportOpen
				? closeSheets()
				: panel !== 'none'
					? (panel = 'none')
					: probe
						? closeInspector()
						: measuring && stopMeasure())}
/>

<div
	class="wrap"
	class:fill={radar}
	class:desk={radar && viewport.desktop}
	class:dark
	bind:this={wrap}
	style:--fill-top="{fillTop}px"
	style:--map-inset="{inset}px"
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
				class:active={measuring}
				aria-pressed={measuring}
				onclick={() => (measuring ? stopMeasure() : startMeasure())}
				title={measuring
					? 'Stop measuring'
					: 'Measure a line: distance, climb and its profile. Or open a GPX track.'}
				aria-label="Measure"
			>
				<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
					><path d="M3.5 16.5l13-13 4 4-13 13zM7.5 12.5l2 2M10.5 9.5l1.5 1.5M13.5 6.5l2 2" /></svg
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
			<LayersSheet
				{analysis}
				contours={contoursReady}
				{offline}
				concern={!!concernCfg}
				ates={!!atesData}
				onclose={() => (panel = 'none')}
			/>
		{/if}

		{#if panel === 'offline'}
			<OfflineMaps
				places={rows
					.filter((r) => r.lat != null && r.lon != null)
					.map((r) => ({ id: r.id, name: r.name, lat: r.lat!, lon: r.lon! }))}
				onclose={() => (panel = 'none')}
			/>
		{/if}

		{#if zoneOpen}
			<ZoneSheet zone={zoneOpen} onclose={() => (zoneOpen = null)} />
		{/if}
		{#if stationOpen}
			<StationSheet station={stationOpen} {units} onclose={() => (stationOpen = null)} />
		{/if}
		{#if reportOpen}
			<ReportSheet report={reportOpen} onclose={() => (reportOpen = null)} />
		{/if}

		{#if askAck && concernCfg}
			<ConcernAck
				caption={concernCfg.caption}
				onaccept={() => prefs.acceptConcern()}
				oncancel={() => prefs.setMapOverlay('none')}
			/>
		{/if}

		<Legend overlay={overlayMode} {units} {zoom} />

		<div class="top">
			{#if locState === 'locating' || locState === 'denied' || locState === 'unavailable' || offline || (on && tooClose)}
				<p class="note glass" role="status">
					{#if on && tooClose && !offline && locState !== 'locating' && locState !== 'denied' && locState !== 'unavailable'}
						Zoom out to see {WEATHER_WORDS[weather]}.
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
					avy={probeAvy}
					concern={probeConcern}
					point={probePoint}
					pointState={probePointState}
					here={probeHere}
					online={(h) => void profileRun(h)}
					onzone={() => (zoneOpen = probeZone)}
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
				{#if weather === 'radar'}
					<p>{radarShown ? `${source} ${RADAR_GAPS}` : source}</p>
					<p>
						Darkest shades: snow {rampTop(RAMPS.snow, units)}, rain {rampTop(RAMPS.rain, units)}.
					</p>
					<p class="faint">
						Snow per hour assumes about 10 parts snow to 1 part water. Beyond about two days the
						frames are 3- and 6-hour averages, and forecasts get rougher the further out they go.
					</p>
				{:else if weather === 'totals'}
					<p>
						Snow total: Canadian models in Canada (HRDPS, then RDPS, then GDPS), with the snow ratio
						from the forecast temperature; NOAA's National Blend of Models in the US; blended across
						the border.
					</p>
					{#if source}<p class="faint">{source}</p>{/if}
					{#if pick?.tiles}
						<p class="faint">
							{TERRAIN_NOTE} Zoomed in, the map shows it that way; tap a spot for the snow at a few heights.
						</p>
					{/if}
				{:else if on && source}
					<p>{source}</p>
					{#if weather === 'snowfall'}
						<p class="faint">
							Snow that fell, analysed from observers' reports and radar. There is no such analysis
							for Canada.
						</p>
					{:else if weather === 'depth'}
						<p class="faint">
							Snow on the ground as modelled daily from observations: 1 km in the US, 2.5 km in
							Canada, so a single slope can differ a lot.
						</p>
					{:else if weather !== 'clouds'}
						<p class="faint">Every 3 hours to about 3½ days. Tap the map for the numbers there.</p>
					{/if}
				{/if}
				<p class="faint">
					Terrain: elevation from Mapterhorn (US lidar to 1 m, Canadian lidar to 2 m, 10–30 m
					elsewhere). Slope and aspect are worked out on this device from about 10 m terrain, so
					small features like cornices and gully walls don't show. Tap the map for the numbers at a
					spot.
				</p>
				<p class="faint">
					Recent satellite: NOAA-20's daily VIIRS mosaic everywhere (375 m), and Sentinel-2 at 10 m
					over the 24 km round each saved location. First the newest clear view, stitched: each
					outlined part is from the newest pass that saw the ground there, dated on the map. Then
					the newest whole scenes that see the area clearly. Contains modified Copernicus Sentinel
					data. Satellite (undated) is Esri's detailed mosaic.
				</p>
				<p class="faint">
					Sun & shade: the sun's position by NOAA's formulas, and shadows cast by terrain up to 15
					km away. Wind effect: how sheltered each slope is from the forecast wind at the nearest
					location's summit, weighted by the snow that wind could move. Both are estimates from the
					shape of the ground, not observations, and say nothing about how stable the snow is.
				</p>
				<p class="faint">
					Huts, trailheads, passes, glaciers, cliffs and ski routes from OpenStreetMap, as mapped by
					volunteers. Snow stations: NRCS SNOTEL and BC River Forecast Centre snow pillows, depth
					now and its change over 24 hours (the dot's colour is the depth; a label is new snow).
					Field reports: Avalanche Canada's Mountain Information Network, the last two weeks, as
					people sent them (US centers' observations need a key: see each center's site).
					{#if atesData}ATES ratings: from files this site's owner downloaded from Avalanche
						Canada's trip planner, as published there.{/if}
					Measure: tap out a line, tap a run or route and choose Profile, or open a GPX track (it stays
					on this device).
				</p>
				<p class="faint">
					Avalanche danger zones and ratings exactly as published by avalanche.org's centers and
					Avalanche Canada (expired ones grey). Avalanche problems shows the terrain a bulletin's
					problems describe, using approximate treeline numbers. Neither rates any slope.
					{#if concernCfg}The concern index is this app's own experimental arithmetic on the
						bulletin and terrain, not a forecast.{/if}
				</p>
				<button class="close" onclick={() => (panel = 'none')}>Close</button>
			</div>
		{/if}

		<div class="dock" bind:this={dock}>
			{#if measuring}
				<Measure
					title={measureTitle}
					note={measureNote}
					{units}
					editing={measureEdit}
					points={measurePts.length}
					samples={measureSamples}
					status={gpxError ? 'failed' : measureState}
					error={gpxError ?? measureError}
					onundo={() => (measurePts = measurePts.slice(0, -1))}
					onclear={() => (measurePts = [])}
					ongpx={(f) => void openGpx(f)}
					onhover={(i) => (measureHover = i)}
					onclose={stopMeasure}
				/>
			{/if}
			{#if recent && !offline}
				<SatControls
					data={satData}
					loadState={satState}
					spot={satSpot}
					bind:index={sceneIndex}
					bands={prefs.satBands}
					{zoom}
					{now}
					onbands={(b) => prefs.setSatBands(b)}
				/>
			{/if}
			{#if avyOverlay && analysis}
				<AvalancheControls
					overlay={overlayMode === 'concern' ? 'concern' : 'problems'}
					{units}
					{zonesState}
					zone={centreZone}
					treeline={centreTreeline}
					tooFar={overlayMode === 'concern' ? zoom < CONCERN_MIN_ZOOM : zoom < OVERLAY_MIN_ZOOM}
					state={areaState}
					bind:pick={problemPick}
					bind:slopeMin={problemSlope}
					concernWhy={concern?.why ?? null}
					windNote={concern?.windNote ?? ''}
					sunNote={concern?.sunNote ?? ''}
					caption={concernCfg?.caption ?? ''}
					onzone={() => (zoneOpen = centreZone)}
				/>
			{/if}
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
					{pointTried}
				/>
			{/if}
			{#if on}
				<TimelineControls
					{view}
					{weather}
					{units}
					bind:frame
					bind:playing
					bind:pickId={() => pick?.id ?? 0, (v) => (picked = { ...picked, [weather]: v })}
					{pick}
					{current}
					{label}
					{waiting}
					snowLine={centreLevel}
					{adjusted}
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
		--ease-slide: 320ms cubic-bezier(0.2, 0.8, 0.2, 1);
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
	/* Desktop: the whole window; the rail floats over the left side. Controls on the left
	   move clear of it (--map-inset). */
	.wrap.fill.desk {
		top: 0;
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
		margin: 10px 0 0 calc(var(--map-inset, 0px) + 10px);
		transition: margin-left var(--ease-slide);
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
		left: calc(var(--map-inset, 0px) + 10px);
		transition: left var(--ease-slide);
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
		left: calc(var(--map-inset, 0px) + 10px);
		transition: left var(--ease-slide);
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
		left: calc(var(--map-inset, 0px) + 60px);
		transition: left var(--ease-slide);
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
		left: calc(var(--map-inset, 0px) + 60px);
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
