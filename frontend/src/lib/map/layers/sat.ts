// The Recent satellite base's layers, bottom first: the daily VIIRS mosaic, the 30 m
// wide view round the location, the Sentinel-2 view over the location's area (each one
// layer of finished tiles), and the stitched views' outlined, dated parts. A new view
// goes on top of the old one of its kind, which stays until the new one's tiles are in,
// so switching views or bands never flashes the coarse mosaic.
import type { GeoJSONSource, Map as MlMap } from 'maplibre-gl';
import type { RecentSource, RecentSpec } from '../sat';

const PREFIX = 'recent-';
const VIEW = `${PREFIX}view-`;
const WIDE = `${PREFIX}wide-`;
/** Layers that hand over to their replacement (see `handOver`). */
const isView = (id: string) => id.startsWith(VIEW) || id.startsWith(WIDE);
/** A replaced view stays at most this long if the new one's tiles are slow. */
const HANDOVER_MS = 6000;

/** The ids of the satellite layers drawn now, bottom first. */
export function recentLayers(map: MlMap): string[] {
	// getLayersOrder, not getStyle: the style would copy every source's data (zones,
	// stations) just to read the ids.
	return map.getLayersOrder().filter((id) => id.startsWith(PREFIX));
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
			...(isView(id) ? { minzoom: src.minzoom } : {}),
			// Never dimmed, even in the dark theme: the point is to see the ground.
			paint: { 'raster-fade-duration': 150 }
		},
		before
	);
}

/** The view of each kind (VIEW, WIDE) each map is showing now, so a late handover never
 *  removes it. */
const current = new WeakMap<MlMap, Record<string, string | null>>();

/** Remove the views of `kind` other than the current one once its tiles are in (or soon). */
function handOver(map: MlMap, id: string, kind: string) {
	let done = false;
	const finish = () => {
		if (done) return;
		done = true;
		map.off('sourcedata', onData);
		clearTimeout(timer);
		const keep = current.get(map)?.[kind];
		for (const old of recentLayers(map)) if (old.startsWith(kind) && old !== keep) remove(map, old);
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
	const wide = spec.wide ? PREFIX + spec.wide.id : null;
	const view = spec.view ? PREFIX + spec.view.id : null;
	for (const id of recentLayers(map)) {
		const gone = id.startsWith(VIEW) ? !view : id.startsWith(WIDE) ? !wide : id !== viirs;
		if (gone) remove(map, id);
	}
	if (spec.viirs && viirs && !map.getLayer(viirs)) {
		// At the bottom, under any view.
		add(map, viirs, spec.viirs, recentLayers(map).find(isView) ?? under);
	}
	current.set(map, { [VIEW]: view, [WIDE]: wide });
	if (spec.wide && wide && !map.getLayer(wide)) {
		// Over the mosaic, under the centre's view.
		add(map, wide, spec.wide, recentLayers(map).find((id) => id.startsWith(VIEW)) ?? under);
		if (recentLayers(map).some((id) => id.startsWith(WIDE) && id !== wide))
			handOver(map, wide, WIDE);
	}
	if (spec.view && view && !map.getLayer(view)) {
		add(map, view, spec.view, under);
		if (recentLayers(map).some((id) => id.startsWith(VIEW) && id !== view))
			handOver(map, view, VIEW);
	}
}

const DATES = 'satdates';
const DATE_LAYERS = ['satdates-casing', 'satdates-line', 'satdates-label'];

/**
 * The stitched views' dashed lines where two passes meet, and each part's date, written
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
	map.addSource(DATES, { type: 'geojson', data, tolerance: 0.5, maxzoom: 12 });
	map.addLayer({
		id: 'satdates-casing',
		type: 'line',
		source: DATES,
		minzoom: 9.5,
		filter: ['==', ['get', 'kind'], 'line'],
		layout: { 'line-join': 'round' },
		// The wide view's lines quieter: there are more of them, and less is at stake.
		paint: {
			'line-color': 'rgba(15, 20, 30, 0.45)',
			'line-width': ['case', ['has', 'wide'], 2.2, 3.2],
			'line-opacity': ['case', ['has', 'wide'], 0.5, 1]
		}
	});
	map.addLayer({
		id: 'satdates-line',
		type: 'line',
		source: DATES,
		minzoom: 9.5,
		filter: ['==', ['get', 'kind'], 'line'],
		layout: { 'line-join': 'round' },
		paint: {
			'line-color': '#ffffff',
			'line-width': ['case', ['has', 'wide'], 1, 1.4],
			'line-opacity': ['case', ['has', 'wide'], 0.6, 1],
			'line-dasharray': [2.5, 2]
		}
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
			'text-size': ['case', ['has', 'wide'], 11.5, ['get', 'newest'], 14, 12.5],
			'text-padding': 24
		},
		paint: {
			'text-color': ['case', ['get', 'newest'], '#fff7c2', '#ffffff'],
			'text-halo-color': 'rgba(15, 20, 30, 0.9)',
			'text-halo-width': 1.8
		}
	});
}
