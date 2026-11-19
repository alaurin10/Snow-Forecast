// Labels over imagery: the server's own rivers, creeks and lakes round the locations
// (OSM_LABELS) replace the tiles' there, so a lake isn't named twice. The file lists the
// boxes it covers; the tiles' water names are left out inside them.
import type { ExpressionSpecification, FilterSpecification, Map as MlMap } from 'maplibre-gl';
import { OSM_LABELS, TILE_WATER_LAYERS } from '../style';

type Box = [number, number, number, number]; // west, south, east, north

/** The boxes as one MultiPolygon, for a `within` filter. */
export function boxesPolygon(boxes: Box[]): GeoJSON.MultiPolygon {
	return {
		type: 'MultiPolygon',
		coordinates: boxes.map(([w, s, e, n]) => [
			[
				[w, s],
				[e, s],
				[e, n],
				[w, n],
				[w, s]
			]
		])
	};
}

/** A layer's filter, less what lies in the boxes. */
export function outside(
	filter: FilterSpecification | undefined,
	boxes: Box[]
): FilterSpecification {
	const away = ['!', ['within', boxesPolygon(boxes)]] as unknown as ExpressionSpecification;
	return (filter ? ['all', filter, away] : away) as FilterSpecification;
}

/** Leave the tiles' water names out where the server names them (once per map). */
export async function useOwnLabels(map: MlMap): Promise<void> {
	let boxes: Box[];
	try {
		const r = await fetch(OSM_LABELS);
		if (!r.ok) return;
		const fc = (await r.json()) as { boxes?: Box[] };
		boxes = (fc.boxes ?? []).filter((b) => Array.isArray(b) && b.length === 4);
	} catch {
		return; // no file yet: the tiles name everything
	}
	if (!boxes.length) return;
	for (const id of TILE_WATER_LAYERS) {
		if (map.getLayer(id)) map.setFilter(id, outside(map.getFilter(id) ?? undefined, boxes));
	}
}
