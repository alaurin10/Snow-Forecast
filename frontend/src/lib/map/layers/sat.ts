// The Recent satellite base's layers: one raster source and layer per tier (and per
// Sentinel-2 tile of the scene shown), kept in order over the base maps and under the
// hill shading. Only what changes is replaced, so stepping to another scene keeps the
// daily mosaic underneath on screen.
import type { Map as MlMap } from 'maplibre-gl';
import type { RecentSource, RecentSpec } from '../sat';

const PREFIX = 'recent-';

function wanted(spec: RecentSpec): { src: RecentSource; minzoom: number; maxzoom?: number }[] {
	const out: { src: RecentSource; minzoom: number; maxzoom?: number }[] = [];
	if (spec.viirs) out.push({ src: spec.viirs, minzoom: 0 });
	// HLS fades in over the coarse mosaic; past zoom 15 its 30 m pixels are just blur
	// (Sentinel-2 is on top there anyway).
	if (spec.hls) out.push({ src: spec.hls, minzoom: spec.hls.minzoom, maxzoom: 16 });
	for (const s of spec.s2) out.push({ src: s, minzoom: s.minzoom + 1 });
	return out;
}

/** The ids of the layers drawn now, bottom first. */
export function recentLayers(map: MlMap): string[] {
	return (map.getStyle()?.layers ?? []).map((l) => l.id).filter((id) => id.startsWith(PREFIX));
}

/**
 * Make the map draw `spec` (empty when the base isn't Recent satellite). `before` is the
 * layer the topmost one goes under.
 */
export function setRecent(map: MlMap, spec: RecentSpec, before?: string) {
	const want = wanted(spec);
	const ids = new Set(want.map((w) => PREFIX + w.src.id));
	for (const id of recentLayers(map)) {
		if (ids.has(id)) continue;
		map.removeLayer(id);
		if (map.getSource(id)) map.removeSource(id);
	}
	// From the top down, each goes just under the one above it.
	let above = before && map.getLayer(before) ? before : undefined;
	for (const w of [...want].reverse()) {
		const id = PREFIX + w.src.id;
		if (map.getLayer(id)) {
			map.moveLayer(id, above);
		} else {
			map.addSource(id, {
				type: 'raster',
				tiles: w.src.tiles,
				tileSize: w.src.tileSize,
				minzoom: w.src.minzoom,
				maxzoom: w.src.maxzoom,
				...(w.src.bounds ? { bounds: w.src.bounds } : {}),
				attribution: w.src.attribution
			});
			map.addLayer(
				{
					id,
					type: 'raster',
					source: id,
					minzoom: w.minzoom,
					...(w.maxzoom ? { maxzoom: w.maxzoom } : {}),
					// Never dimmed, even in the dark theme: the point is to see the ground.
					paint: { 'raster-fade-duration': 150 }
				},
				above
			);
		}
		above = id;
	}
}
