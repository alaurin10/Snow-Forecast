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

/** How strongly each weather layer covers the map, by zoom. */
export function weatherOpacity(w: string): ExpressionSpecification {
	if (w === 'radar') return PRECIP_OPACITY;
	if (w === 'clouds') return CLOUD_OPACITY;
	if (w === 'totals' || w === 'snowfall') return TOTAL_OPACITY;
	return FIELD_OPACITY;
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
export const PEAK_LAYERS = ['peaks', 'peak-labels'];
/** Huts and shelters, trailheads and passes. */
export const PLACE_LAYERS = ['places', 'place-labels'];
export const GLACIER_LAYERS = ['glaciers', 'glacier-lines', 'cliffs', 'glacier-labels'];
export const CONTOUR_LAYERS = ['contour-lines', 'contour-labels'];
/** The precipitation overlay goes under this layer (over the base and terrain overlays). */
export const PRECIP_BEFORE = 'satlabels';

export const ELEVATION_ATTRIBUTION =
	'Elevation © <a href="https://mapterhorn.com/attribution/">Mapterhorn</a> (USGS 3DEP, NRCan HRDEM, Copernicus and others)';

/** The ski map's features (runs, routes, huts …), as the server serves them. */
export const SKI_DATA = '/api/osm/ski.geojson';

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

/** Hill shading lit by the sun where it really is (compass degrees, degrees up). */
export function sunPaint(azimuth: number, altitude: number, dark: boolean) {
	return {
		// Brightness by the angle the light strikes the ground at.
		'hillshade-method': 'basic' as const,
		'hillshade-exaggeration': 0.3,
		'hillshade-illumination-direction': Math.round(azimuth) % 360,
		// Very low light would blacken every slope turned slightly away.
		'hillshade-illumination-altitude': Math.min(90, Math.max(8, altitude)),
		'hillshade-illumination-anchor': 'map' as const,
		'hillshade-shadow-color': dark ? '#000000' : '#1d2333',
		'hillshade-highlight-color': dark ? 'rgba(255,244,214,0.2)' : 'rgba(255,244,214,0.45)',
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
		satlabels: {
			type: 'raster',
			tiles: tiles('satlabels'),
			tileSize: 256,
			maxzoom: 18,
			attribution: 'Labels © <a href="https://www.esri.com">Esri</a>'
		},
		// Runs, lifts, peaks, huts, glaciers and more from OpenStreetMap, fetched weekly by
		// the server.
		ski: {
			type: 'geojson',
			data: SKI_DATA,
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
			maxzoom: DETAIL_ZOOM + 1,
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
	layers.push({
		id: 'satlabels',
		type: 'raster',
		source: 'satlabels',
		layout: { visibility: vis(imagery) },
		paint: { 'raster-fade-duration': 150 }
	});
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

function contourLayers(dark: boolean, units: UnitSystem, on: boolean): LayerSpecification[] {
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
			id: 'peaks',
			type: 'circle',
			source: 'ski',
			minzoom: 10,
			filter: ['==', ['get', 'kind'], 'peak'],
			layout: { visibility: pv },
			paint: {
				'circle-radius': 3,
				'circle-color': peakColor(dark),
				'circle-stroke-width': 1.2,
				'circle-stroke-color': halo(dark)
			}
		},
		{
			id: 'peak-labels',
			type: 'symbol',
			source: 'ski',
			minzoom: 10,
			filter: ['==', ['get', 'kind'], 'peak'],
			layout: {
				visibility: pv,
				'text-field': peakLabel(units),
				'text-font': FONT,
				'text-size': ['interpolate', ['linear'], ['zoom'], 10, 10.5, 15, 13],
				'text-anchor': 'top',
				'text-offset': [0, 0.5],
				'text-max-width': 8
			},
			paint: {
				'text-color': peakText(dark),
				'text-halo-color': halo(dark),
				'text-halo-width': 1.6
			}
		}
	];
}

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
