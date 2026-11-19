// The Recent satellite base's layers, bottom first: the daily VIIRS mosaic, every
// location's 30 m wide view, every location's 10 m view (each one layer of finished
// tiles), and the nearest location's outlined, dated parts. New views go on top of the
// ones they replace, which stay until the new ones' tiles are in, so switching views or
// bands never flashes the coarse mosaic.
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

/** The views each map is showing now, so a late handover never removes them. */
const current = new WeakMap<MlMap, Set<string>>();

/** Remove the views no longer wanted once the new ones' tiles are in (or soon), so a
 *  change of view or bands never flashes what's under it. */
function handOver(map: MlMap, fresh: string[]) {
	let done = false;
	const finish = () => {
		if (done) return;
		done = true;
		map.off('sourcedata', onData);
		clearTimeout(timer);
		const keep = current.get(map) ?? new Set();
		for (const old of recentLayers(map)) if (isView(old) && !keep.has(old)) remove(map, old);
	};
	const loaded = () => fresh.every((id) => !map.getSource(id) || map.isSourceLoaded(id));
	const onData = (e: { sourceId?: string }) => {
		if (e.sourceId && fresh.includes(e.sourceId) && loaded()) finish();
	};
	const timer = setTimeout(finish, HANDOVER_MS);
	map.on('sourcedata', onData);
}

/**
 * Make the map draw `spec` (empty when the base isn't Recent satellite). `before` is the
 * layer the satellite goes under (the hill shading).
 */
export function setRecent(map: MlMap, spec: RecentSpec, before?: string) {
	const under = before && map.getLayer(before) ? before : undefined;
	const viirs = spec.viirs ? PREFIX + spec.viirs.id : null;
	// Source ids start `wide-` or `view-`, so these start WIDE or VIEW.
	const wanted = [...spec.wides, ...spec.views].map((src) => ({ id: PREFIX + src.id, src }));
	const ids = new Set(wanted.map((w) => w.id));
	for (const id of recentLayers(map)) if (!isView(id) && id !== viirs) remove(map, id);
	if (spec.viirs && viirs && !map.getLayer(viirs)) {
		// At the bottom, under any view.
		add(map, viirs, spec.viirs, recentLayers(map).find(isView) ?? under);
	}
	current.set(map, ids);
	const fresh: string[] = [];
	for (const { id, src } of wanted) {
		if (!map.getLayer(id)) {
			add(map, id, src, under);
			fresh.push(id);
		}
	}
	// Bottom first, just under `under` (each move puts the layer above the ones moved
	// before it): views being replaced just under their own kind's new ones, so while
	// the new tiles load the old 10 m view still covers the 30 m ones.
	const stale = recentLayers(map).filter((id) => isView(id) && !ids.has(id));
	const kind = (k: string) => (id: string) => id.startsWith(k);
	const wantedIds = wanted.map((w) => w.id);
	for (const id of [
		...stale.filter(kind(WIDE)),
		...wantedIds.filter(kind(WIDE)),
		...stale.filter(kind(VIEW)),
		...wantedIds.filter(kind(VIEW))
	])
		map.moveLayer(id, under);
	if (!stale.length) return;
	if (fresh.length) handOver(map, fresh);
	else for (const id of stale) remove(map, id);
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
