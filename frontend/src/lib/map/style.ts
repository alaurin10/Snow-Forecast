// The map's style: base maps, elevation, terrain overlays, contours and the ski layer.
// Pure functions of the viewer's choices, so MapView can build the style once and then
// flip visibility and paint as choices change.
import type {
	ExpressionSpecification,
	LayerSpecification,
	SourceSpecification,
	StyleSpecification
} from 'maplibre-gl';
import type { UnitSystem } from '../units';
import type { MapBase, MapOverlay, MapShade } from '../prefs.svelte';
import { AWS_DEM, MAX_ZOOM } from './terrain/dem';
import { ANALYSIS_ZOOM } from './terrain/analysis';
import { dusk } from './terrain/shade';
import { BIG_PARKS, PLACES_MAX_ZOOM, PLACES_TILES } from './placeTiles';

/** From here in, OpenTopoMap's detail (contours, trails, peaks, lifts) takes over. */
export const DETAIL_ZOOM = 12;
export const PISTE_ZOOM = 11;
/** Contours start here; below it they'd be a tangle. */
export const CONTOUR_ZOOM = 11;
/** A little extra height reads well zoomed out without making couloirs cartoonish up close. */
export const EXAGGERATION = 1.15;

export const TOTAL_OPACITY: ExpressionSpecification = [
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
export const PRECIP_OPACITY: ExpressionSpecification = [
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

/** Snow level, wind and snow on the ground: smooth fields, under the labels. */
export const FIELD_OPACITY: ExpressionSpecification = [
	'interpolate',
	['linear'],
	['zoom'],
	10,
	0.62,
	13,
	0.45,
	15,
	0
];
/** Temperature: a field like the snow level, but adjusted to the terrain zoomed in, so it
 *  stays (lighter) however far in. */
export const TEMP_OPACITY: ExpressionSpecification = [
	'interpolate',
	['linear'],
	['zoom'],
	10,
	0.62,
	14,
	0.45
];
/** Satellite imagery of clouds: nearly opaque, gone by the time terrain detail matters. */
export const CLOUD_OPACITY: ExpressionSpecification = [
	'interpolate',
	['linear'],
	['zoom'],
	9,
	0.85,
	11,
	0.6,
	13,
	0
];

/** Forecast clouds drawn from numbers: as the pictures zoomed out; zoomed in, the cloud
 *  against the terrain (fog on the ground inside it), which stays on further in but
 *  lighter, so the ground under the fog still reads. */
export const CLOUD_NUMBERS_OPACITY: ExpressionSpecification = [
	'interpolate',
	['linear'],
	['zoom'],
	9,
	0.85,
	12,
	0.75,
	15,
	0.5,
	16.5,
	0
];

/** How strongly each weather layer covers the map, by zoom. */
export function weatherOpacity(w: string): ExpressionSpecification {
	if (w === 'radar') return PRECIP_OPACITY;
	if (w === 'clouds') return CLOUD_OPACITY;
	if (w === 'totals' || w === 'snowfall') return TOTAL_OPACITY;
	if (w === 'temp') return TEMP_OPACITY;
	return FIELD_OPACITY;
}

/** An opacity-by-zoom ramp's value at a zoom (a layer we draw ourselves needs the number). */
export function opacityAt(opacity: ExpressionSpecification, zoom: number): number {
	const e = opacity as unknown[];
	if (e[0] !== 'interpolate') return typeof opacity === 'number' ? opacity : 1;
	const stops = e.slice(3) as number[];
	if (zoom <= stops[0]) return stops[1];
	for (let i = 2; i < stops.length; i += 2) {
		if (zoom <= stops[i]) {
			const f = (zoom - stops[i - 2]) / (stops[i] - stops[i - 2]);
			return stops[i - 1] + (stops[i + 1] - stops[i - 1]) * f;
		}
	}
	return stops[stops.length - 1];
}

/**
 * The zoom where an opacity-by-zoom ramp reaches 0 for good, as a layer's maxzoom: past
 * it the layer is invisible, so MapLibre needn't draw it or keep its tiles. 24 (no limit)
 * if the ramp doesn't end at 0.
 */
export function goneAt(opacity: ExpressionSpecification): number {
	const e = opacity as unknown[];
	const [z, v] = e.slice(-2);
	return e[0] === 'interpolate' && v === 0 && typeof z === 'number' ? z : 24;
}

/** Cross-fade from Esri over half a zoom level. */
export const OTM_OPACITY: ExpressionSpecification = [
	'interpolate',
	['linear'],
	['zoom'],
	DETAIL_ZOOM - 0.5,
	0,
	DETAIL_ZOOM + 0.3,
	1
];

export const SKI_LAYERS = [
	'run-casing',
	'runs',
	'lifts',
	'routes',
	'run-labels',
	'lift-labels',
	'route-labels'
];
export const PEAK_LAYERS = ['peak-labels'];
/** The peaks' dot: an SDF image, coloured by the layer (see peakDot). */
export const PEAK_DOT = 'peak-dot';

/** A round dot as a signed distance field, for PEAK_DOT: drawn at half its pixels, 3 px
 *  across the middle, with room for the halo round it. */
export function peakDot(): { width: number; height: number; data: Uint8Array } {
	const size = 24;
	const r = 6;
	const data = new Uint8Array(size * size * 4);
	for (let y = 0; y < size; y++) {
		for (let x = 0; x < size; x++) {
			const d = Math.hypot(x + 0.5 - size / 2, y + 0.5 - size / 2);
			// MapLibre's SDF edge is at 192; outward it fades for the halo.
			data[(y * size + x) * 4 + 3] = Math.max(0, Math.min(255, Math.round(192 + (r - d) * 24)));
		}
	}
	return { width: size, height: size, data };
}
/** Huts and shelters, trailheads and passes. */
export const PLACE_LAYERS = ['places', 'place-labels'];
export const GLACIER_LAYERS = ['glaciers', 'glacier-lines', 'cliffs', 'glacier-labels'];
export const CONTOUR_LAYERS = ['contour-lines', 'contour-labels'];
/** Names and borders over imagery (OpenStreetMap vector tiles): what Esri's Boundaries
 *  & Places pictures showed but county lines. State, province and country lines; park,
 *  wilderness and forest names; rivers, creeks and lakes; state and town names. Bottom
 *  first, so towns win when names collide. (Peaks are the ski map's own layer.) */
export const SAT_LABEL_LAYERS = [
	'satlabels',
	'satlabels-borders',
	'satlabels-countries',
	'satlabels-parks',
	'satlabels-park-areas',
	'satlabels-small-parks',
	'satlabels-local-parks',
	'satlabels-rivers',
	'satlabels-lakes',
	'satlabels-lake-lines',
	'satlabels-own-rivers',
	'satlabels-own-lakes',
	'satlabels-states',
	'satlabels-towns'
];
/** State, province and country lines: shown over imagery whatever the Names switch. */
export const SAT_BORDER_LAYERS = SAT_LABEL_LAYERS.slice(0, 3);
/** The names over imagery, which the Names switch (`names` feature) shows or hides. */
export const SAT_NAME_LAYERS = SAT_LABEL_LAYERS.slice(3);
/** The precipitation overlay goes under this layer (over the base and terrain overlays). */
export const PRECIP_BEFORE = SAT_LABEL_LAYERS[0];

export const ELEVATION_ATTRIBUTION =
	'Elevation © <a href="https://mapterhorn.com/attribution/">Mapterhorn</a> (USGS 3DEP, NRCan HRDEM, Copernicus and others)';

/** The ski map's features (runs, routes, huts …), as the server serves them. */
export const SKI_DATA = '/api/osm/ski.geojson';
/** Rivers, creeks and lakes round the locations, named over imagery. */
export const OSM_LABELS = '/api/osm/labels.geojson';
/** GeoJSON sources are cut into tiles to this zoom (MapLibre's default is 18) and
 *  stretched beyond it. Tiles at a source's maxzoom aren't simplified, so what's drawn
 *  is the same. */
export const GEOJSON_ZOOM = 14;

// Base map and ski-run tiles come through the server, which caches them.
const tiles = (layer: string) => [`/api/tiles/${layer}/{z}/{x}/{y}.png`];

export interface StyleOptions {
	dark: boolean;
	/** The full map (all layers and controls) rather than the small overview map. */
	full: boolean;
	units: UnitSystem;
	base: MapBase;
	runs: boolean;
	peaks: boolean;
	/** Huts, trailheads and passes. */
	places: boolean;
	/** Glaciers and cliffs. */
	glaciers: boolean;
	/** Place, water and park names over imagery (borders show whatever this is). */
	names?: boolean;
	contours: boolean;
	shade: MapShade;
	overlay: MapOverlay;
	/** Elevation comes through the terrain worker (dem://); false on old browsers. */
	worker: boolean;
	/** maplibre-contour's tile URL, when contours are available. */
	contourTiles?: string;
}

/** Dimmed a little in the dark theme so the map doesn't glare. */
export function basePaint(dark: boolean, darkBrightness = 0.72) {
	return {
		'raster-brightness-max': dark ? darkBrightness : 1,
		'raster-saturation': dark ? -0.15 : 0
	} as const;
}

/** The 3D sky and haze. `clearGround` keeps the haze off the terrain (recent satellite). */
export function sky(dark: boolean, clearGround = false): StyleSpecification['sky'] {
	return {
		'sky-color': dark ? '#0d1626' : '#9cc6ec',
		'horizon-color': dark ? '#2a3a52' : '#e4eef7',
		'fog-color': dark ? '#1b2638' : '#dfe8f0',
		'sky-horizon-blend': 0.6,
		'horizon-fog-blend': 0.6,
		// 1 puts the start of the haze at the horizon: none over the ground itself.
		'fog-ground-blend': clearGround ? 1 : 0.8,
		'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 10, 1, 12, 0]
	};
}

const vis = (on: boolean) => (on ? 'visible' : 'none') as 'visible' | 'none';

/** Elevation sources: one for 3D, one for shading and bands (MapLibre advises keeping them apart). */
export function demSources(worker: boolean): Record<string, SourceSpecification> {
	if (!worker) {
		// Old browsers: AWS terrain straight, as before the terrain worker.
		const aws = {
			type: 'raster-dem' as const,
			tiles: [`${AWS_DEM}/{z}/{x}/{y}.png`],
			encoding: 'terrarium' as const,
			tileSize: 256,
			maxzoom: 15,
			attribution: 'Terrain: <a href="https://registry.opendata.aws/terrain-tiles/">Mapzen, AWS</a>'
		};
		return { dem: aws, demshade: { ...aws, maxzoom: 14 } };
	}
	const dem = {
		type: 'raster-dem' as const,
		tiles: ['dem://{z}/{x}/{y}'],
		encoding: 'terrarium' as const,
		tileSize: 512,
		// 1 m US lidar at 16, 2 m Canadian lidar at 15; the worker fills in where it's coarser.
		maxzoom: MAX_ZOOM,
		attribution: ELEVATION_ATTRIBUTION
	};
	return { dem, demshade: { ...dem, maxzoom: MAX_ZOOM - 1 } };
}

/** Hillshade strength for each setting. */
export function shadePaint(shade: MapShade, dark: boolean, base: MapBase) {
	// Esri topo is already shaded; satellite imagery has its own shadows. Both want less.
	const k = shade === 'strong' ? 1 : 0.55;
	const imagery = base !== 'topo';
	return {
		'hillshade-method': 'igor' as const,
		'hillshade-exaggeration': imagery ? imageryShade(k) : 0.35 * k,
		// The map-drawing convention: lit from the top-left of the screen.
		'hillshade-illumination-direction': 335,
		'hillshade-illumination-altitude': 45,
		'hillshade-illumination-anchor': 'viewport' as const,
		// Over a photo, a softer shadow: it adds relief without darkening the picture.
		'hillshade-shadow-color': dark
			? imagery
				? '#0d1016'
				: '#000000'
			: imagery
				? '#4a5262'
				: '#2a2f3a',
		'hillshade-highlight-color': dark ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.35)',
		'hillshade-accent-color': dark
			? imagery
				? '#0d1016'
				: '#000000'
			: imagery
				? '#565b67'
				: '#3b3f4a'
	};
}

/** Hillshade over imagery, by zoom. MapLibre steepens the slopes it shades zoomed out
 *  and relaxes them toward z15, so one fixed strength darkened the photo zoomed out and
 *  barely touched it up close: the picture brightened as you zoomed in. This ramps the
 *  other way so the tone stays even. */
export function imageryShade(k: number): ExpressionSpecification {
	const r = (x: number) => Math.round(x * k * 1000) / 1000;
	return ['interpolate', ['linear'], ['zoom'], 7, r(0.12), 11, r(0.25), 14, r(0.45)];
}

/**
 * Hill shading lit by the sun where it really is (compass degrees, degrees up). One way of
 * shading from sunrise to sunset and on below the horizon: as the sun drops the light
 * keeps its direction (it never falls below 8°, where every slope turned slightly away
 * would go black) and its warm highlights fade, so the map only grows darker.
 */
export function sunPaint(azimuth: number, altitude: number, dark: boolean) {
	// Full in daylight, none once the sun has set, as the shade darkens (shade.ts).
	const hi = (dark ? 0.2 : 0.45) * (1 - dusk(altitude));
	return {
		// Brightness by the angle the light strikes the ground at.
		'hillshade-method': 'basic' as const,
		'hillshade-exaggeration': 0.3,
		'hillshade-illumination-direction': Math.round(azimuth) % 360,
		'hillshade-illumination-altitude': Math.min(90, Math.max(8, altitude)),
		'hillshade-illumination-anchor': 'map' as const,
		'hillshade-shadow-color': dark ? '#000000' : '#1d2333',
		'hillshade-highlight-color': `rgba(255,244,214,${Math.round(hi * 1000) / 1000})`,
		'hillshade-accent-color': dark ? '#000000' : '#3b3f4a'
	};
}

/** How strongly each whole-view analysis picture is laid over the map. */
export const ANALYSIS_OPACITY = { shade: 0.42, hours: 0.6, wind: 0.75, concern: 0.8 } as const;
/** Whole-view layers are worked out from this zoom in; further out they'd say little. */
export const SUN_MIN_ZOOM = 9;
export const WIND_MIN_ZOOM = 10;
/** The concern index needs the wind grid's detail. */
export const CONCERN_MIN_ZOOM = 10;
/** Terrain tile overlays (slope, aspect, avalanche problems) start here. */
export const OVERLAY_MIN_ZOOM = 8;

/**
 * Elevation bands: a colour every 500 m (metric) or 1,500 ft (imperial), as hard steps.
 * Returns the colour expression and the band list for the legend.
 */
export function elevationBands(units: UnitSystem) {
	const ft = units === 'imperial';
	const stepM = ft ? 1500 / 3.28084 : 500;
	const colors = [
		'#3a8f5a',
		'#7cb04d',
		'#c6c84a',
		'#e8b84a',
		'#e08a3c',
		'#b5643a',
		'#8c5a4a',
		'#a99aa6',
		'#e6e3ee'
	];
	const bands = colors.map((color, i) => {
		const from = i * stepM;
		const label = ft
			? `${(i * 1500).toLocaleString('en-US')}${i === colors.length - 1 ? '+' : ''} ft`
			: `${(i * 500).toLocaleString('en-US')}${i === colors.length - 1 ? '+' : ''} m`;
		return { from, color, label };
	});
	const stops: (number | string)[] = [];
	bands.forEach((b, i) => {
		if (i > 0) stops.push(b.from - 0.5, bands[i - 1].color);
		stops.push(b.from, b.color);
	});
	const expr = [
		'interpolate',
		['linear'],
		['elevation'],
		...stops
	] as unknown as ExpressionSpecification;
	return { expr, bands };
}

export function overlayTiles(mode: 'slope' | 'aspect' | 'match', query = ''): string[] {
	return [`terrain://${mode}/{z}/{x}/{y}${query ? `?${query}` : ''}`];
}

export function mapStyle(o: StyleOptions): StyleSpecification {
	const full = o.full;
	const topo = !full || o.base === 'topo';
	const sat = full && o.base === 'satellite';
	/** Imagery of some kind: place names go over it, and contours. */
	const imagery = full && o.base !== 'topo';
	const sources: StyleSpecification['sources'] = {
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
		labels: {
			type: 'vector',
			tiles: ['/api/tiles/labels/{z}/{x}/{y}.pbf'],
			maxzoom: 14,
			attribution:
				'Labels: <a href="https://openfreemap.org">OpenFreeMap</a>, <a href="https://www.openmaptiles.org/">© OpenMapTiles</a>, data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
		},
		// The same tiles stretched from zoom 8: only those name every national park and
		// forest and wilderness (later tiles keep a park's name point in one tile, and
		// drop the big ones), so these names stay on as the map zooms in.
		'labels-z8': {
			type: 'vector',
			tiles: ['/api/tiles/labels/{z}/{x}/{y}.pbf'],
			maxzoom: 8
		},
		// Towns and hamlets from the next zoom's tiles (placeTiles.ts): those list the
		// smaller places a zoom sooner (zoom 8's leave out Redmond, zoom 10's the hamlets).
		'labels-fine': { type: 'vector', tiles: [PLACES_TILES], maxzoom: PLACES_MAX_ZOOM },
		// Rivers, creeks and lakes round the locations, which the tiles name too late or
		// in pieces (backend/snowwatch/osmlabels.py).
		osmlabels: { type: 'geojson', data: OSM_LABELS, maxzoom: GEOJSON_ZOOM, tolerance: 0.5 },
		// Runs, lifts, peaks, huts, glaciers and more from OpenStreetMap, fetched weekly by
		// the server.
		ski: {
			type: 'geojson',
			data: SKI_DATA,
			// Cut into tiles to zoom 14 (about 20 cm a unit here) and stretched beyond, rather
			// than cut again at every zoom to 18.
			maxzoom: GEOJSON_ZOOM,
			attribution:
				'Runs, lifts, peaks, huts, glaciers © <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>'
		},
		...demSources(o.worker)
	};
	const layers: LayerSpecification[] = [
		{
			id: 'esri',
			type: 'raster',
			source: 'esri',
			// OpenTopoMap covers it from DETAIL_ZOOM + 0.3 (OTM_OPACITY): no Esri tiles are
			// fetched or drawn under it after that.
			maxzoom: DETAIL_ZOOM + 0.5,
			layout: { visibility: vis(topo) },
			paint: { 'raster-fade-duration': 150, ...basePaint(o.dark) }
		},
		{
			id: 'otm',
			type: 'raster',
			source: 'otm',
			minzoom: DETAIL_ZOOM - 0.5,
			layout: { visibility: vis(topo) },
			paint: { 'raster-opacity': OTM_OPACITY, 'raster-fade-duration': 150, ...basePaint(o.dark) }
		},
		// Satellite: imagery, then place names and borders over it (and over the
		// precipitation, so names stay readable).
		{
			id: 'sat',
			type: 'raster',
			source: 'sat',
			layout: { visibility: vis(sat) },
			paint: { 'raster-fade-duration': 150, ...basePaint(o.dark, 0.8) }
		}
	];
	if (full) {
		const { expr } = elevationBands(o.units);
		layers.push(
			{
				id: 'shade',
				type: 'hillshade',
				source: 'demshade',
				layout: { visibility: vis(o.shade !== 'off' && o.base !== 'recent') },
				paint: shadePaint(o.shade === 'off' ? 'light' : o.shade, o.dark, o.base)
			},
			{
				id: 'bands',
				type: 'color-relief',
				source: 'demshade',
				layout: { visibility: vis(o.overlay === 'bands') },
				paint: { 'color-relief-color': expr, 'color-relief-opacity': 0.5 }
			}
		);
		if (o.worker) {
			sources.overlay = {
				type: 'raster',
				tiles: overlayTiles(o.overlay === 'aspect' ? 'aspect' : 'slope'),
				tileSize: 512,
				maxzoom: ANALYSIS_ZOOM,
				attribution: ELEVATION_ATTRIBUTION
			};
			layers.push({
				id: 'overlay',
				type: 'raster',
				source: 'overlay',
				minzoom: 8,
				layout: { visibility: vis(o.overlay === 'slope' || o.overlay === 'aspect') },
				paint: {
					'raster-opacity': ['interpolate', ['linear'], ['zoom'], 8, 0, 9, 0.6, 15, 0.5],
					// Crisp class edges when zoomed past the analysis grid.
					'raster-resampling': 'nearest',
					'raster-fade-duration': 0
				}
			});
		}
	}
	layers.push(...satLabelLayers(imagery, o.names ?? true));
	if (full && o.contourTiles) {
		sources.contours = { type: 'vector', tiles: [o.contourTiles], maxzoom: 15 };
		layers.push(...contourLayers(o.dark, o.units, o.contours && imagery));
	}
	if (full) layers.push(...glacierLayers(o.dark, o.glaciers));
	layers.push(...skiLayers(o.dark, o.units, full && o.runs, !full || o.peaks));
	if (full) layers.push(...placeLayers(o.dark, o.units, o.places));
	return {
		version: 8,
		sources,
		layers,
		glyphs: '/api/glyphs/{fontstack}/{range}.pbf',
		sky: sky(o.dark, full && o.base === 'recent')
	};
}

// ---- Contours (maplibre-contour, from the same elevation) -------------------------

/** Contour spacing [minor, major] by zoom, in the viewer's units. */
export function contourThresholds(units: UnitSystem): Record<number, [number, number]> {
	return units === 'imperial'
		? { 11: [200, 1000], 12: [100, 500], 14: [40, 200], 15: [20, 100] }
		: { 11: [50, 250], 12: [50, 250], 13: [20, 100], 15: [10, 50] };
}

export function contourColor(dark: boolean) {
	return dark ? 'rgba(255,240,220,0.55)' : 'rgba(255,245,230,0.7)';
}

export function contourLayers(dark: boolean, units: UnitSystem, on: boolean): LayerSpecification[] {
	const unit = units === 'imperial' ? ' ft' : ' m';
	return [
		{
			id: 'contour-lines',
			type: 'line',
			source: 'contours',
			'source-layer': 'contours',
			minzoom: CONTOUR_ZOOM,
			layout: { visibility: vis(on) },
			paint: {
				'line-color': contourColor(dark),
				'line-width': ['match', ['get', 'level'], 1, 1.1, 0.5]
			}
		},
		{
			id: 'contour-labels',
			type: 'symbol',
			source: 'contours',
			'source-layer': 'contours',
			minzoom: 12.5,
			filter: ['>', ['get', 'level'], 0],
			layout: {
				visibility: vis(on),
				'symbol-placement': 'line',
				'text-size': 10.5,
				'text-field': ['concat', ['number-format', ['get', 'ele'], {}], unit],
				'text-font': ['Noto Sans Regular']
			},
			paint: {
				'text-color': '#fff6e8',
				'text-halo-color': 'rgba(30,25,20,0.75)',
				'text-halo-width': 1.2
			}
		}
	];
}

// ---- Runs, lifts and peaks (vector, so names follow the runs and stay upright) -----
const RUN = ['==', ['get', 'kind'], 'run'] as unknown as ExpressionSpecification;
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
const LABEL_PAINT = {
	'text-halo-color': 'rgba(255,255,255,0.95)',
	'text-halo-width': 2,
	'text-halo-blur': 0.2
};

export const halo = (dark: boolean) => (dark ? 'rgba(10,15,25,0.85)' : 'rgba(255,255,255,0.9)');
export const peakColor = (dark: boolean) => (dark ? '#e8edf5' : '#3a3346');
export const peakText = (dark: boolean) => (dark ? '#eef2f8' : '#2a2433');

export function peakLabel(units: UnitSystem): ExpressionSpecification {
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

export function skiLayers(
	dark: boolean,
	units: UnitSystem,
	runs: boolean,
	peaks: boolean
): LayerSpecification[] {
	const v = vis(runs);
	const pv = vis(peaks);
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
	return [
		{
			id: 'run-casing',
			type: 'line',
			source: 'ski',
			minzoom: PISTE_ZOOM,
			filter: RUN,
			layout: { visibility: v, 'line-cap': 'round', 'line-join': 'round' },
			paint: { 'line-color': halo(dark), 'line-width': lineWidth(2) }
		},
		{
			id: 'runs',
			type: 'line',
			source: 'ski',
			minzoom: PISTE_ZOOM,
			filter: RUN,
			layout: { visibility: v, 'line-cap': 'round', 'line-join': 'round' },
			paint: {
				'line-color': runColor,
				'line-width': lineWidth(0),
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
			layout: { visibility: v },
			paint: {
				'line-color': '#d6303a',
				'line-width': ['interpolate', ['linear'], ['zoom'], 11, 1, 16, 2.5]
			}
		},
		{
			// Ski routes made of many ways (route=ski|piste), so a tour has its name.
			id: 'routes',
			type: 'line',
			source: 'ski',
			minzoom: 10,
			filter: ['==', ['get', 'kind'], 'route'],
			layout: { visibility: v, 'line-cap': 'round', 'line-join': 'round' },
			paint: {
				'line-color': '#7b3fb0',
				'line-opacity': 0.8,
				'line-width': ['interpolate', ['linear'], ['zoom'], 10, 1.2, 15, 2.6],
				'line-dasharray': [1, 2]
			}
		},
		{
			id: 'run-labels',
			type: 'symbol',
			source: 'ski',
			minzoom: 13,
			filter: ['all', RUN, ['!=', ['get', 'name'], '']],
			layout: {
				visibility: v,
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
				visibility: v,
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
			id: 'route-labels',
			type: 'symbol',
			source: 'ski',
			minzoom: 12,
			filter: ['all', ['==', ['get', 'kind'], 'route'], ['!=', ['get', 'name'], '']],
			layout: {
				visibility: v,
				'symbol-placement': 'line',
				'text-field': ['get', 'name'],
				'text-font': FONT,
				'text-size': 11.5,
				'text-pitch-alignment': 'viewport',
				'symbol-spacing': 400,
				'text-offset': [0, -0.9]
			},
			paint: { 'text-color': '#6a2f9e', ...LABEL_PAINT }
		},
		{
			// The dot is the label's icon, so a peak whose name has no room shows nothing
			// rather than a nameless dot.
			id: 'peak-labels',
			type: 'symbol',
			source: 'ski',
			minzoom: 9,
			filter: PEAK_FILTER,
			layout: {
				visibility: pv,
				// The highest first where names would overlap.
				'symbol-sort-key': ['-', 0, ['coalesce', ['get', 'ele'], 0]],
				'icon-image': PEAK_DOT,
				'text-field': peakLabel(units),
				'text-font': FONT,
				'text-size': ['interpolate', ['linear'], ['zoom'], 10, 10.5, 15, 13],
				'text-anchor': 'top',
				'text-offset': [0, 0.5],
				'text-max-width': 8,
				// Room round each name, more zoomed out, so the peaks shown stand apart.
				'text-padding': ['interpolate', ['linear'], ['zoom'], 10, 10, 14, 3]
			},
			paint: {
				'icon-color': peakColor(dark),
				'icon-halo-color': halo(dark),
				'icon-halo-width': 1.2,
				'text-color': peakText(dark),
				'text-halo-color': halo(dark),
				'text-halo-width': 1.6
			}
		}
	];
}

/**
 * Peaks by isolation (`iso`, km to the nearest higher peak; snowwatch/osm.py): zoomed
 * out only the big, standalone ones (15 km at zoom 9, 6 at 10, 3 at 11, 1.2 at 12, 0.5
 * at 13), every named peak from zoom 14. A file from before isolation shows them all.
 */
export const PEAK_FILTER = [
	'all',
	['==', ['get', 'kind'], 'peak'],
	[
		'>=',
		['coalesce', ['get', 'iso'], 1000],
		['step', ['zoom'], 15, 10, 6, 11, 3, 12, 1.2, 13, 0.5, 14, 0]
	]
] as ExpressionSpecification;

// ---- Glaciers and cliffs; huts, trailheads and passes --------------------------------

const kindIs = (k: string) => ['==', ['get', 'kind'], k] as unknown as ExpressionSpecification;

export function glacierLayers(dark: boolean, on: boolean): LayerSpecification[] {
	const v = vis(on);
	return [
		{
			id: 'glaciers',
			type: 'fill',
			source: 'ski',
			minzoom: 8,
			filter: kindIs('glacier'),
			layout: { visibility: v },
			paint: {
				'fill-color': dark ? '#8fc8ee' : '#d9f0ff',
				'fill-opacity': ['interpolate', ['linear'], ['zoom'], 8, 0.5, 14, dark ? 0.16 : 0.35]
			}
		},
		{
			id: 'glacier-lines',
			type: 'line',
			source: 'ski',
			minzoom: 9,
			filter: kindIs('glacier'),
			layout: { visibility: v },
			paint: { 'line-color': '#4f9fd1', 'line-width': 0.9, 'line-dasharray': [3, 1.5] }
		},
		{
			id: 'cliffs',
			type: 'line',
			source: 'ski',
			minzoom: 12,
			filter: kindIs('cliff'),
			layout: { visibility: v, 'line-cap': 'round' },
			paint: {
				'line-color': dark ? '#d8c3a5' : '#4a3a2c',
				'line-width': ['interpolate', ['linear'], ['zoom'], 12, 1, 16, 2.4]
			}
		},
		{
			id: 'glacier-labels',
			type: 'symbol',
			source: 'ski',
			minzoom: 11,
			filter: ['all', kindIs('glacier'), ['!=', ['get', 'name'], '']],
			layout: {
				visibility: v,
				'text-field': ['get', 'name'],
				'text-font': ['Noto Sans Regular'],
				'text-size': 11.5,
				'text-max-width': 8
			},
			paint: {
				'text-color': dark ? '#bfe3fb' : '#2a6f9e',
				'text-halo-color': halo(dark),
				'text-halo-width': 1.4
			}
		}
	];
}

/** Colours of huts, trailheads and passes on the map and in its key. */
export const PLACE_COLORS = { hut: '#9a4e1c', trailhead: '#2f8f3f', pass: '#6b4fa0' } as const;

export function placeLabel(units: UnitSystem): ExpressionSpecification {
	const ft = units === 'imperial';
	return [
		'case',
		['all', ['has', 'ele'], ['!=', ['get', 'kind'], 'trailhead']],
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

export function placeLayers(dark: boolean, units: UnitSystem, on: boolean): LayerSpecification[] {
	const v = vis(on);
	const filter = [
		'match',
		['get', 'kind'],
		['hut', 'trailhead', 'pass'],
		true,
		false
	] as unknown as ExpressionSpecification;
	return [
		{
			id: 'places',
			type: 'circle',
			source: 'ski',
			minzoom: 10,
			filter,
			layout: { visibility: v },
			paint: {
				'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 3.5, 15, 6],
				'circle-color': [
					'match',
					['get', 'kind'],
					'hut',
					PLACE_COLORS.hut,
					'trailhead',
					PLACE_COLORS.trailhead,
					PLACE_COLORS.pass
				],
				'circle-stroke-width': 1.6,
				'circle-stroke-color': '#ffffff'
			}
		},
		{
			id: 'place-labels',
			type: 'symbol',
			source: 'ski',
			minzoom: 11.5,
			filter: ['all', filter, ['!=', ['get', 'name'], '']],
			layout: {
				visibility: v,
				'text-field': placeLabel(units),
				'text-font': FONT,
				'text-size': 11.5,
				'text-anchor': 'top',
				'text-offset': [0, 0.6],
				'text-max-width': 9,
				'text-optional': true
			},
			paint: {
				'text-color': peakText(dark),
				'text-halo-color': halo(dark),
				'text-halo-width': 1.5
			}
		}
	];
}

/** Borders of states, provinces and countries: not counties (admin_level 6) or sea
 *  limits. */
/** The tiles' river and lake names, which the map leaves out round the locations, where
 *  `osmlabels` names them whole (layers/labels.ts). */
export const TILE_WATER_LAYERS = ['satlabels-rivers', 'satlabels-lakes', 'satlabels-lake-lines'];

/** Parks named from the zoom-8 tiles (`labels-z8`), and in each quarter they cover. */

const BORDERS = [
	'all',
	['<=', ['coalesce', ['get', 'admin_level'], 99], 4],
	['!=', ['get', 'maritime'], 1]
] as ExpressionSpecification;

/** How far apart the tiles' river and long lake names repeat along them, in screen
 *  pixels (wider zoomed in, where a river crosses the screen in long bends). */
const LINE_LABEL_SPACING = [
	'interpolate',
	['linear'],
	['zoom'],
	10,
	350,
	13,
	450,
	16,
	900
] as ExpressionSpecification;

/** Water names: light blue on a dark halo, as Esri drew them. */
const WATER_TEXT = {
	'text-color': '#a9dcff',
	'text-halo-color': 'rgba(10, 25, 45, 0.9)',
	'text-halo-width': 1.4
};

/**
 * Names and borders over imagery, from OpenStreetMap, at about the zooms Esri's label
 * pictures showed them: state and country lines (light, on a dark casing, dashed for
 * states); park, wilderness and national forest names (green, zoom 8 to 12); rivers
 * from 11 and creeks from 13 along their lines; lakes; state names when zoomed out; and
 * towns, more of them as the map zooms in.
 */
export function satLabelLayers(on: boolean, names = true): LayerSpecification[] {
	const bv = vis(on);
	const v = vis(on && names);
	const country = ['==', ['coalesce', ['get', 'admin_level'], 99], 2] as ExpressionSpecification;
	return [
		{
			id: 'satlabels',
			type: 'line',
			source: 'labels',
			'source-layer': 'boundary',
			filter: BORDERS,
			layout: { visibility: bv, 'line-join': 'round' },
			paint: {
				'line-color': 'rgba(15, 20, 30, 0.55)',
				'line-width': [
					'interpolate',
					['linear'],
					['zoom'],
					4,
					['case', country, 3, 2.2],
					12,
					['case', country, 5, 3.6]
				]
			}
		},
		{
			id: 'satlabels-borders',
			type: 'line',
			source: 'labels',
			'source-layer': 'boundary',
			filter: ['all', BORDERS, ['>', ['coalesce', ['get', 'admin_level'], 99], 2]],
			layout: { visibility: bv, 'line-join': 'round' },
			paint: {
				'line-color': 'rgba(255, 255, 255, 0.85)',
				'line-width': ['interpolate', ['linear'], ['zoom'], 4, 1, 12, 1.8],
				'line-dasharray': [4, 2.5]
			}
		},
		{
			// Country lines solid, over the dashes, so a state line along one doesn't dash it.
			id: 'satlabels-countries',
			type: 'line',
			source: 'labels',
			'source-layer': 'boundary',
			filter: ['all', BORDERS, country],
			layout: { visibility: bv, 'line-join': 'round' },
			paint: {
				'line-color': 'rgba(255, 255, 255, 0.9)',
				'line-width': ['interpolate', ['linear'], ['zoom'], 4, 1.4, 12, 2.4]
			}
		},
		{
			// National parks and forests, wildernesses and protected areas, by their label
			// points (polygons would be named again in every tile they cross), from the
			// zoom-8 tiles (see `labels-z8`).
			id: 'satlabels-parks',
			type: 'symbol',
			source: 'labels-z8',
			'source-layer': 'park',
			minzoom: 8,
			maxzoom: 10,
			filter: [
				'all',
				['==', ['geometry-type'], 'Point'],
				['in', ['get', 'class'], ['literal', BIG_PARKS]]
			],
			layout: {
				visibility: v,
				'text-field': ['get', 'name'],
				'text-font': ['Noto Sans Regular'],
				'text-size': 11.5,
				'text-max-width': 7,
				'text-padding': 6,
				'text-optional': true
			},
			paint: {
				'text-color': '#c9eba6',
				'text-halo-color': 'rgba(12, 30, 12, 0.85)',
				'text-halo-width': 1.3
			}
		},
		{
			// From zoom 10 the big parks are named in each 256 px quarter they cover, as
			// Esri's pictures did (placeTiles.ts), so a national forest's name is on screen
			// wherever it is (it has one name point, often far away).
			id: 'satlabels-park-areas',
			type: 'symbol',
			source: 'labels-fine',
			'source-layer': 'park_label',
			minzoom: 10,
			layout: {
				visibility: v,
				'text-field': ['get', 'name'],
				'text-font': ['Noto Sans Regular'],
				'text-size': 11.5,
				'text-max-width': 7,
				'text-padding': 30,
				'text-optional': true
			},
			paint: {
				'text-color': '#c9eba6',
				'text-halo-color': 'rgba(12, 30, 12, 0.85)',
				'text-halo-width': 1.3
			}
		},
		{
			// Smaller parks, state forests and reserves, from the tiles of the map's zoom.
			id: 'satlabels-small-parks',
			type: 'symbol',
			source: 'labels',
			'source-layer': 'park',
			minzoom: 9,
			// By their name points to zoom 12; then inside each tile they cover (later
			// tiles keep a park's name point in one tile only).
			filter: [
				'all',
				['!', ['in', ['get', 'class'], ['literal', BIG_PARKS]]],
				[
					'any',
					['all', ['==', ['geometry-type'], 'Point'], ['<', ['zoom'], 12]],
					['all', ['==', ['geometry-type'], 'Polygon'], ['>=', ['zoom'], 12]]
				]
			],
			layout: {
				visibility: v,
				'text-field': ['get', 'name'],
				'text-font': ['Noto Sans Regular'],
				'text-size': 10.5,
				'text-max-width': 7,
				'text-padding': 6,
				'text-optional': true
			},
			paint: {
				'text-color': '#c9eba6',
				'text-halo-color': 'rgba(12, 30, 12, 0.85)',
				'text-halo-width': 1.2
			}
		},
		{
			// Town parks and golf courses from zoom 13, from the next zoom's tiles
			// (placeTiles.ts), which list them.
			id: 'satlabels-local-parks',
			type: 'symbol',
			source: 'labels-fine',
			'source-layer': 'poi',
			minzoom: 13,
			layout: {
				visibility: v,
				'text-field': ['get', 'name'],
				'text-font': ['Noto Sans Regular'],
				'text-size': 11,
				'text-max-width': 7,
				'text-padding': 2,
				// Beside the place when the middle is taken (a town's name is often there).
				'text-variable-anchor': ['center', 'left', 'right', 'top', 'bottom'],
				'text-radial-offset': 0.4,
				'text-justify': 'auto'
			},
			paint: {
				'text-color': '#c9eba6',
				'text-halo-color': 'rgba(12, 30, 12, 0.85)',
				'text-halo-width': 1.2
			}
		},
		{
			id: 'satlabels-rivers',
			type: 'symbol',
			source: 'labels',
			'source-layer': 'waterway',
			minzoom: 11,
			filter: [
				'any',
				['==', ['get', 'class'], 'river'],
				['all', ['==', ['get', 'class'], 'stream'], ['>=', ['zoom'], 13]]
			],
			layout: {
				visibility: v,
				'symbol-placement': 'line',
				// OpenStreetMap's streams wind more than the default 45° a letter allows.
				'text-max-angle': 85,
				'text-field': ['get', 'name'],
				'text-font': ['Noto Sans Regular'],
				'text-size': ['match', ['get', 'class'], 'river', 12, 11],
				'text-letter-spacing': 0.05,
				'symbol-spacing': LINE_LABEL_SPACING
			},
			paint: { ...WATER_TEXT }
		},
		{
			// Small lakes come as points…
			id: 'satlabels-lakes',
			type: 'symbol',
			source: 'labels',
			'source-layer': 'water_name',
			minzoom: 11,
			filter: ['==', ['geometry-type'], 'Point'],
			layout: {
				visibility: v,
				'text-field': ['get', 'name'],
				'text-font': ['Noto Sans Regular'],
				'text-size': 11.5,
				'text-max-width': 7
			},
			paint: { ...WATER_TEXT }
		},
		{
			// …big ones as a line along the lake, the name written along it (again along a
			// long lake, as Esri's were).
			id: 'satlabels-lake-lines',
			type: 'symbol',
			source: 'labels',
			'source-layer': 'water_name',
			minzoom: 9,
			filter: ['==', ['geometry-type'], 'LineString'],
			layout: {
				visibility: v,
				'symbol-placement': 'line',
				'symbol-spacing': LINE_LABEL_SPACING,
				'text-max-angle': 85,
				'text-field': ['get', 'name'],
				'text-font': ['Noto Sans Regular'],
				'text-size': 12,
				'text-letter-spacing': 0.05
			},
			paint: { ...WATER_TEXT }
		},
		{
			// Round the locations: rivers from zoom 10 and creeks from 12, along their
			// whole length (the tiles cut them into pieces too short for a name).
			id: 'satlabels-own-rivers',
			type: 'symbol',
			source: 'osmlabels',
			minzoom: 10,
			filter: [
				'all',
				['==', ['get', 'kind'], 'water'],
				['any', ['==', ['get', 'class'], 'river'], ['>=', ['zoom'], 12]]
			],
			layout: {
				visibility: v,
				// Once along each stretch on screen (the middle of its piece in each map
				// tile), not repeated every few hundred pixels.
				'symbol-placement': 'line-center',
				'text-max-angle': 85,
				'text-field': ['get', 'name'],
				'text-font': ['Noto Sans Regular'],
				'text-size': ['match', ['get', 'class'], 'river', 12, 11],
				'text-letter-spacing': 0.05
			},
			paint: { ...WATER_TEXT }
		},
		{
			// Lakes by size: 5 km² and more from zoom 10, 1 km² from 11, 0.1 km² from 12,
			// the rest from 13.
			id: 'satlabels-own-lakes',
			type: 'symbol',
			source: 'osmlabels',
			minzoom: 10,
			filter: [
				'all',
				['==', ['get', 'kind'], 'lake'],
				[
					'any',
					['>=', ['zoom'], 13],
					['all', ['>=', ['zoom'], 12], ['>=', ['get', 'area'], 0.1]],
					['all', ['>=', ['zoom'], 11], ['>=', ['get', 'area'], 1]],
					['>=', ['get', 'area'], 5]
				]
			],
			layout: {
				visibility: v,
				'text-field': ['get', 'name'],
				'text-font': ['Noto Sans Regular'],
				'text-size': ['interpolate', ['linear'], ['get', 'area'], 0, 11, 5, 12.5],
				'text-max-width': 7
			},
			paint: { ...WATER_TEXT }
		},
		{
			id: 'satlabels-states',
			type: 'symbol',
			source: 'labels',
			'source-layer': 'place',
			maxzoom: 8,
			filter: ['in', ['get', 'class'], ['literal', ['state', 'province']]],
			layout: {
				visibility: v,
				'text-field': ['get', 'name'],
				'text-font': FONT,
				'text-size': 12,
				'text-letter-spacing': 0.12,
				'text-transform': 'uppercase',
				'text-max-width': 8
			},
			paint: {
				'text-color': 'rgba(255, 255, 255, 0.85)',
				'text-halo-color': 'rgba(15, 20, 30, 0.8)',
				'text-halo-width': 1.4
			}
		},
		{
			// From the next zoom's tiles (`labels-fine`), which list more places; the more
			// important first where names would overlap.
			id: 'satlabels-towns',
			type: 'symbol',
			source: 'labels-fine',
			'source-layer': 'place',
			// Only the major cities zoomed out (rank 10 and under: Seattle, Tacoma,
			// Everett), then other cities from zoom 9, towns from 10, villages from 10.5
			// and hamlets from 11.
			filter: [
				'any',
				['all', ['==', ['get', 'class'], 'city'], ['<=', ['coalesce', ['get', 'rank'], 99], 10]],
				['all', ['==', ['get', 'class'], 'city'], ['>=', ['zoom'], 9]],
				['all', ['==', ['get', 'class'], 'town'], ['>=', ['zoom'], 10]],
				['all', ['==', ['get', 'class'], 'village'], ['>=', ['zoom'], 10.5]],
				['all', ['==', ['get', 'class'], 'hamlet'], ['>=', ['zoom'], 11]]
			],
			layout: {
				visibility: v,
				'text-field': ['get', 'name'],
				'text-font': FONT,
				// A name moves beside its place if the middle is taken.
				'text-size': [
					'interpolate',
					['linear'],
					['zoom'],
					8,
					['match', ['get', 'class'], 'city', 12.5, 10.5],
					11,
					['match', ['get', 'class'], 'city', 13.5, 'town', 12, 11]
				],
				'text-variable-anchor': ['center', 'left', 'right', 'top', 'bottom'],
				'text-radial-offset': 0.4,
				'text-justify': 'auto',
				'text-max-width': 8,
				'text-padding': 4,
				'symbol-sort-key': ['coalesce', ['get', 'rank'], 20]
			},
			paint: {
				'text-color': '#fff6e0',
				'text-halo-color': 'rgba(15, 20, 30, 0.85)',
				'text-halo-width': 1.5
			}
		}
	];
}
