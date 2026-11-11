// Wiring the terrain layers into a map: the worker's protocols, contours, and the
// changes that follow the viewer's choices (overlay, shading, contours, units).
import type { Map as MlMap, RasterTileSource, VectorTileSource } from 'maplibre-gl';
import type { UnitSystem } from '../../units';
import type { MapOverlay, MapShade } from '../../prefs.svelte';
import { registerProtocols } from '../terrain/client';
import { BASE_ZOOM, MAPTERHORN } from '../terrain/dem';
import {
	CONTOUR_LAYERS,
	contourColor,
	contourThresholds,
	elevationBands,
	overlayTiles,
	shadePaint
} from '../style';

type MapLibre = typeof import('maplibre-gl');

type DemSource = InstanceType<(typeof import('maplibre-contour'))['default']['DemSource']>;
let contourSource: DemSource | null = null;
let contourLoading: Promise<void> | null = null;

/**
 * Get the page ready for terrain: the dem:// and terrain:// protocols (false on
 * browsers without the worker), and maplibre-contour, loaded on demand.
 */
export async function setupTerrain(ml: MapLibre): Promise<{ worker: boolean }> {
	const worker = registerProtocols(ml);
	if (!contourLoading) {
		contourLoading = import('maplibre-contour')
			.then((mod) => {
				const mlcontour = mod.default;
				const src = new mlcontour.DemSource({
					url: `${MAPTERHORN}/{z}/{x}/{y}.webp`,
					encoding: 'terrarium',
					// Everywhere has zoom 12; finer contours would mostly trace lidar noise.
					maxzoom: BASE_ZOOM,
					worker: true,
					cacheSize: 60
				});
				src.setupMaplibre(ml as never);
				contourSource = src;
			})
			.catch((e) => console.error('contours', e));
	}
	await contourLoading;
	return { worker };
}

export function contourTiles(units: UnitSystem): string | undefined {
	return contourSource?.contourProtocolUrl({
		multiplier: units === 'imperial' ? 3.28084 : 1,
		thresholds: contourThresholds(units),
		contourLayer: 'contours',
		elevationKey: 'ele',
		levelKey: 'level',
		// Half the 512 px tiles' work, and smoother lines.
		overzoom: 1
	});
}

const vis = (on: boolean) => (on ? 'visible' : 'none');

export function setOverlay(map: MlMap, overlay: MapOverlay) {
	if (map.getLayer('bands')) map.setLayoutProperty('bands', 'visibility', vis(overlay === 'bands'));
	const src = map.getSource('overlay') as RasterTileSource | undefined;
	if (!src || !map.getLayer('overlay')) return;
	const on = overlay === 'slope' || overlay === 'aspect';
	if (on) {
		const want = overlayTiles(overlay);
		if (JSON.stringify(src.tiles) !== JSON.stringify(want)) src.setTiles(want);
	}
	map.setLayoutProperty('overlay', 'visibility', vis(on));
}

export function setShade(map: MlMap, shade: MapShade, dark: boolean, base: 'topo' | 'satellite') {
	if (!map.getLayer('shade')) return;
	map.setLayoutProperty('shade', 'visibility', vis(shade !== 'off'));
	if (shade === 'off') return;
	for (const [k, v] of Object.entries(shadePaint(shade, dark, base)))
		map.setPaintProperty('shade', k as never, v as never);
}

export function setContours(map: MlMap, on: boolean, dark: boolean) {
	for (const id of CONTOUR_LAYERS)
		if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis(on));
	if (map.getLayer('contour-lines'))
		map.setPaintProperty('contour-lines', 'line-color', contourColor(dark));
}

/** Contour spacing, contour labels and elevation bands in the viewer's units. */
export function setTerrainUnits(map: MlMap, units: UnitSystem) {
	const src = map.getSource('contours') as VectorTileSource | undefined;
	const t = contourTiles(units);
	if (src && t && src.tiles?.[0] !== t) src.setTiles([t]);
	if (map.getLayer('contour-labels'))
		map.setLayoutProperty('contour-labels', 'text-field', [
			'concat',
			['number-format', ['get', 'ele'], {}],
			units === 'imperial' ? ' ft' : ' m'
		]);
	if (map.getLayer('bands'))
		map.setPaintProperty('bands', 'color-relief-color', elevationBands(units).expr);
}
