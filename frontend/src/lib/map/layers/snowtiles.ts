// Terrain-adjusted snow totals (docs/MAP-PLAN.md A4): zoomed in, the Snow total layer
// switches from the server's one picture of the whole box (model cells of 2.5–15 km) to
// tiles the server paints from the window's snow by elevation and the terrain, so peaks
// get the snow above the snow level and valleys below it don't.
import type { ExpressionSpecification, Map as MlMap, RasterSourceSpecification } from 'maplibre-gl';

export const SNOWTILES_ID = 'snowtiles';
/** What the tiles show, in words (the plan's caption). */
export const TERRAIN_NOTE =
	"Adjusted to terrain: model precipitation, snow above the model's snow level.";
/** From this zoom in, the tiles replace the picture. */
export const SNOWTILES_ZOOM = 8;
/** The server draws tiles to zoom 11 (about 25 m a pixel here); MapLibre stretches them beyond. */
const TILE_MAX_ZOOM = 11;

/** A total's tiles to use at this zoom, or null for the picture. */
export function snowTilesUrl(
	total: { tiles?: string | null } | undefined,
	zoom: number
): string | null {
	return total?.tiles && zoom >= SNOWTILES_ZOOM ? total.tiles : null;
}

/**
 * Show a total's terrain-adjusted tiles from SNOWTILES_ZOOM in (null hides them), under
 * `beforeId`, with the precipitation picture's opacity. The picture is limited to zooms
 * below SNOWTILES_ZOOM while the tiles show, so the two never draw at once.
 */
export function setSnowTiles(
	map: MlMap,
	tiles: string | null,
	opts: {
		bounds: [[number, number], [number, number]];
		opacity: ExpressionSpecification;
		beforeId?: string;
		pictureId: string;
	}
): void {
	const src = map.getSource(SNOWTILES_ID) as
		(RasterSourceSpecification & { tiles?: string[] }) | undefined;
	// (The picture's layer is remade when the box changes, so this is set every time.)
	if (map.getLayer(opts.pictureId))
		map.setLayerZoomRange(opts.pictureId, 0, tiles ? SNOWTILES_ZOOM : 24);
	const current = map.getLayer(SNOWTILES_ID) ? (src?.tiles?.[0] ?? null) : null;
	if (current === tiles) return;
	if (map.getLayer(SNOWTILES_ID)) map.removeLayer(SNOWTILES_ID);
	if (map.getSource(SNOWTILES_ID)) map.removeSource(SNOWTILES_ID);
	if (!tiles) return;
	const [[south, west], [north, east]] = opts.bounds;
	map.addSource(SNOWTILES_ID, {
		type: 'raster',
		tiles: [tiles],
		tileSize: 512,
		// A 512 px tile at zoom z serves the map at zoom z + 1.
		minzoom: SNOWTILES_ZOOM - 1,
		maxzoom: TILE_MAX_ZOOM,
		bounds: [west, south, east, north]
	});
	map.addLayer(
		{
			id: SNOWTILES_ID,
			type: 'raster',
			source: SNOWTILES_ID,
			minzoom: SNOWTILES_ZOOM,
			paint: {
				'raster-opacity': opts.opacity,
				'raster-fade-duration': 0,
				'raster-resampling': 'linear'
			}
		},
		opts.beforeId && map.getLayer(opts.beforeId) ? opts.beforeId : undefined
	);
}

/**
 * Snow (cm) at an elevation from a point's numbers by elevation (every 250 m from 0),
 * linear between them; null without them.
 */
export function snowAtElevation(
	byElevation: number[] | null | undefined,
	elevations: number[],
	m: number | null | undefined
): number | null {
	if (!byElevation || m == null || !Number.isFinite(m) || byElevation.length !== elevations.length)
		return null;
	if (!elevations.length) return null;
	if (m <= elevations[0]) return byElevation[0];
	for (let i = 1; i < elevations.length; i++) {
		if (m <= elevations[i]) {
			const f = (m - elevations[i - 1]) / (elevations[i] - elevations[i - 1]);
			return byElevation[i - 1] + (byElevation[i] - byElevation[i - 1]) * f;
		}
	}
	return byElevation[byElevation.length - 1];
}

/**
 * A few round elevations around a spot (metres) to show snow at: every 500 m (or 1,500 ft)
 * from about 1,000 m (3,000 ft) below it to as far above, within the numbers' range.
 */
export function elevationLadder(spot: number, imperial: boolean, top = 4500): number[] {
	const step = imperial ? 1500 * 0.3048 : 500;
	const first = Math.max(1, Math.ceil((spot - 2 * step) / step));
	const out: number[] = [];
	for (let i = first; out.length < 4; i++) {
		const m = i * step;
		if (m > top) break;
		out.push(m);
	}
	return out;
}
