// The Recent satellite base's layers: the daily VIIRS mosaic, the Sentinel-2 view over
// the location's area (one layer of finished tiles), and the stitched view's outlined,
// dated parts. A new view goes on top of the old one, which stays until the new one's
// tiles are in, so switching views or bands never flashes the coarse mosaic.
import type { GeoJSONSource, Map as MlMap } from 'maplibre-gl';
import type { RecentSource, RecentSpec } from '../sat';

const PREFIX = 'recent-';
const VIEW = `${PREFIX}view-`;
/** A replaced view stays at most this long if the new one's tiles are slow. */
const HANDOVER_MS = 6000;

/** The ids of the satellite layers drawn now, bottom first. */
export function recentLayers(map: MlMap): string[] {
	return (map.getStyle()?.layers ?? []).map((l) => l.id).filter((id) => id.startsWith(PREFIX));
}

function remove(map: MlMap, id: string) {
	if (map.getLayer(id)) map.removeLayer(id);
	if (map.getSource(id)) map.removeSource(id);
}

function add(map: MlMap, id: string, src: RecentSource, before?: string) {
	map.addSource(id, {
		type: 'raster',
		tiles: src.tiles,
		tileSize: src.tileSize,
		minzoom: src.minzoom,
		maxzoom: src.maxzoom,
		...(src.bounds ? { bounds: src.bounds } : {}),
		attribution: src.attribution
	});
	map.addLayer(
		{
			id,
			type: 'raster',
			source: id,
			...(id.startsWith(VIEW) ? { minzoom: src.minzoom } : {}),
			// Never dimmed, even in the dark theme: the point is to see the ground.
			paint: { 'raster-fade-duration': 150 }
		},
		before
	);
}

/** The view each map is showing now, so a late handover never removes it. */
const current = new WeakMap<MlMap, string | null>();

/** Remove the views other than the current one once its tiles are in (or soon). */
function handOver(map: MlMap, id: string) {
	let done = false;
	const finish = () => {
		if (done) return;
		done = true;
		map.off('sourcedata', onData);
		clearTimeout(timer);
		const keep = current.get(map);
		for (const old of recentLayers(map)) if (old.startsWith(VIEW) && old !== keep) remove(map, old);
	};
	const onData = (e: { sourceId?: string }) => {
		if (e.sourceId === id && map.getSource(id) && map.isSourceLoaded(id)) finish();
	};
	const timer = setTimeout(finish, HANDOVER_MS);
	map.on('sourcedata', onData);
}

/**
 * Make the map draw `spec` (all nulls when the base isn't Recent satellite). `before`
 * is the layer the satellite goes under (the hill shading).
 */
export function setRecent(map: MlMap, spec: RecentSpec, before?: string) {
	const under = before && map.getLayer(before) ? before : undefined;
	const viirs = spec.viirs ? PREFIX + spec.viirs.id : null;
	const view = spec.view ? PREFIX + spec.view.id : null;
	for (const id of recentLayers(map)) {
		if (id.startsWith(VIEW) ? !view : id !== viirs) remove(map, id);
	}
	if (spec.viirs && viirs && !map.getLayer(viirs)) {
		// At the bottom, under any view.
		const firstView = recentLayers(map).find((id) => id.startsWith(VIEW));
		add(map, viirs, spec.viirs, firstView ?? under);
	}
	current.set(map, view);
	if (spec.view && view && !map.getLayer(view)) {
		add(map, view, spec.view, under);
		if (recentLayers(map).some((id) => id.startsWith(VIEW) && id !== view)) handOver(map, view);
	}
}

const DATES = 'satdates';
const DATE_LAYERS = ['satdates-casing', 'satdates-line', 'satdates-label'];

/**
 * The stitched view's dashed lines where two passes meet, and each part's date, written
 * wherever the part is on screen (null removes them). Drawn from zoom 9.5.
 */
export function setRecentDates(map: MlMap, data: GeoJSON.FeatureCollection | null) {
	const src = map.getSource(DATES) as GeoJSONSource | undefined;
	if (!data) {
		for (const id of [...DATE_LAYERS].reverse()) if (map.getLayer(id)) map.removeLayer(id);
		if (src) map.removeSource(DATES);
		return;
	}
	if (src) {
		src.setData(data);
		return;
	}
	map.addSource(DATES, { type: 'geojson', data, tolerance: 0.5 });
	map.addLayer({
		id: 'satdates-casing',
		type: 'line',
		source: DATES,
		minzoom: 9.5,
		filter: ['==', ['get', 'kind'], 'line'],
		layout: { 'line-join': 'round' },
		paint: { 'line-color': 'rgba(15, 20, 30, 0.45)', 'line-width': 3.2 }
	});
	map.addLayer({
		id: 'satdates-line',
		type: 'line',
		source: DATES,
		minzoom: 9.5,
		filter: ['==', ['get', 'kind'], 'line'],
		layout: { 'line-join': 'round' },
		paint: { 'line-color': '#ffffff', 'line-width': 1.4, 'line-dasharray': [2.5, 2] }
	});
	map.addLayer({
		id: 'satdates-label',
		type: 'symbol',
		source: DATES,
		minzoom: 9.5,
		filter: ['==', ['get', 'kind'], 'part'],
		layout: {
			// A polygon's label goes at the middle of its piece in each map tile, so a part
			// keeps a date in view as the map pans.
			'text-field': ['get', 'label'],
			'text-font': ['Open Sans Semibold'],
			'text-size': ['case', ['get', 'newest'], 14, 12.5],
			'text-padding': 24
		},
		paint: {
			'text-color': ['case', ['get', 'newest'], '#fff7c2', '#ffffff'],
			'text-halo-color': 'rgba(15, 20, 30, 0.9)',
			'text-halo-width': 1.8
		}
	});
}
