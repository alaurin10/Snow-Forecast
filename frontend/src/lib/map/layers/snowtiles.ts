// Terrain-adjusted snow totals (docs/MAP-PLAN.md A4): zoomed in, the Snow total layer
// switches from the server's one picture of the whole box (model cells of 2.5–15 km) to
// tiles the server paints from the window's snow by elevation and the terrain, so peaks
// get the snow above the snow level and valleys below it don't.
import type { ExpressionSpecification, Map as MlMap, RasterTileSource } from 'maplibre-gl';
import { goneAt } from '../style';

/** Each window's tiles are a source and layer of their own: this, then its tiles' id. */
export const SNOWTILES_ID = 'snowtiles';
/** What the tiles show, in words (the plan's caption). */
export const TERRAIN_NOTE =
	"Adjusted to terrain: model precipitation, snow above the model's snow level.";
/** From this zoom in, the tiles replace the picture. */
export const SNOWTILES_ZOOM = 8;
/** The server draws tiles to zoom 11 (about 25 m a pixel here); MapLibre stretches them beyond. */
const TILE_MAX_ZOOM = 11;
/** A replaced window stays at most this long if the new one's tiles are slow. */
const HANDOVER_MS = 8000;
/** Tiles that failed (the server busy drawing, or its elevation source slow) are asked
 *  for again after these waits; then not until the map moves. */
const RETRY_MS = [1500, 4000, 10000];

/** A total's tiles to use at this zoom, or null for the picture. */
export function snowTilesUrl(
	total: { tiles?: string | null } | undefined,
	zoom: number
): string | null {
	return total?.tiles && zoom >= SNOWTILES_ZOOM ? total.tiles : null;
}

/** The layer id for a window's tiles (its URL holds the tiles' id, which changes with the
 *  forecast and the window). A new id is what makes MapLibre draw the new window into
 *  3D terrain at once: under the same id it took the old window's drape to be current. */
export function snowTilesId(tiles: string): string {
	const id = /\/api\/snowtiles\/([0-9a-f]+)\//.exec(tiles)?.[1];
	return `${SNOWTILES_ID}-${id ?? tiles.replace(/[^\w]/g, '').slice(-24)}`;
}

/** The snow-tile layers on the map, bottom first. */
export function snowTileLayers(map: MlMap): string[] {
	return map.getLayersOrder().filter((id) => id.startsWith(`${SNOWTILES_ID}-`));
}

function remove(map: MlMap, id: string) {
	if (map.getLayer(id)) map.removeLayer(id);
	if (map.getSource(id)) map.removeSource(id);
}

/** What each map shows now, so a late hand-over never removes it. */
const current = new WeakMap<MlMap, string | null>();
/** Each map's retry and hand-over watchers, to stop when the tiles change again. */
const watching = new WeakMap<MlMap, () => void>();

/** Drop the other windows once the new one's tiles are in (or soon), and ask again for
 *  tiles that failed. */
function watch(map: MlMap, id: string, tiles: string) {
	watching.get(map)?.();
	let tries = 0;
	let retry: ReturnType<typeof setTimeout> | undefined;
	let handed = false;
	const handOver = () => {
		if (handed) return;
		handed = true;
		clearTimeout(timer);
		const keep = current.get(map);
		for (const old of snowTileLayers(map)) if (old !== keep) remove(map, old);
	};
	const onData = (e: { sourceId?: string }) => {
		if (e.sourceId === id && map.getSource(id) && map.isSourceLoaded(id)) handOver();
	};
	// A tile's failure arrives as the map's "error" event, carrying the source's id.
	const onError = (ev: object) => {
		const e = ev as { sourceId?: string };
		if (e.sourceId !== id || retry || tries >= RETRY_MS.length) return;
		retry = setTimeout(() => {
			retry = undefined;
			tries++;
			const src = map.getSource(id) as RasterTileSource | undefined;
			// The same URL again: tiles drawn already come from the browser's cache.
			if (src && current.get(map) === id) src.setTiles([tiles]);
		}, RETRY_MS[tries]);
	};
	const timer = setTimeout(handOver, HANDOVER_MS);
	map.on('sourcedata', onData);
	map.on('error', onError);
	watching.set(map, () => {
		clearTimeout(timer);
		clearTimeout(retry);
		map.off('sourcedata', onData);
		map.off('error', onError);
	});
}

/**
 * Show a total's terrain-adjusted tiles from SNOWTILES_ZOOM in (null hides them), under
 * `beforeId`, with the precipitation picture's opacity, up to where that fades out. (The
 * caller limits the picture to zooms below SNOWTILES_ZOOM while the tiles show, so the two
 * never draw at once.) A new window goes over the one showing, which stays until the new
 * one's tiles are in, so a change of window is never blank.
 */
export function setSnowTiles(
	map: MlMap,
	tiles: string | null,
	opts: {
		bounds: [[number, number], [number, number]];
		opacity: ExpressionSpecification;
		beforeId?: string;
	}
): void {
	const id = tiles ? snowTilesId(tiles) : null;
	if (id && current.get(map) === id && map.getLayer(id)) return;
	current.set(map, id);
	if (!tiles || !id) {
		watching.get(map)?.();
		watching.delete(map);
		for (const old of snowTileLayers(map)) remove(map, old);
		return;
	}
	const [[south, west], [north, east]] = opts.bounds;
	remove(map, id);
	map.addSource(id, {
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
			id,
			type: 'raster',
			source: id,
			minzoom: SNOWTILES_ZOOM,
			maxzoom: goneAt(opts.opacity),
			paint: {
				'raster-opacity': opts.opacity,
				'raster-fade-duration': 0,
				'raster-resampling': 'linear'
			}
		},
		opts.beforeId && map.getLayer(opts.beforeId) ? opts.beforeId : undefined
	);
	watch(map, id, tiles);
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
