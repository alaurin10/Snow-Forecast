// The measured line on the map: coloured by the slope of the ground it crosses, the points
// tapped out (while measuring), and the spot the profile's crosshair is on. Drawn over
// everything else.
import type { GeoJSONSource, Map as MlMap } from 'maplibre-gl';
import type { LngLat } from '../measure';

const LINE = 'measure-line';
const POINTS = 'measure-points';
const HOVER = 'measure-hover';
const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

export interface MeasureDrawing {
	/** The sampled line in coloured stretches; before sampling, the plain line. */
	line: GeoJSON.FeatureCollection;
	/** The points tapped out, while they can still be changed. */
	points: LngLat[];
	hover: LngLat | null;
}

function ensure(map: MlMap) {
	if (map.getSource(LINE)) return;
	map.addSource(LINE, { type: 'geojson', data: EMPTY });
	map.addSource(POINTS, { type: 'geojson', data: EMPTY });
	map.addSource(HOVER, { type: 'geojson', data: EMPTY });
	map.addLayer({
		id: 'measure-casing',
		type: 'line',
		source: LINE,
		layout: { 'line-cap': 'round', 'line-join': 'round' },
		paint: { 'line-color': '#ffffff', 'line-width': 7, 'line-opacity': 0.9 }
	});
	map.addLayer({
		id: LINE,
		type: 'line',
		source: LINE,
		layout: { 'line-cap': 'round', 'line-join': 'round' },
		paint: { 'line-color': ['coalesce', ['get', 'color'], '#4b3fb5'], 'line-width': 4 }
	});
	map.addLayer({
		id: POINTS,
		type: 'circle',
		source: POINTS,
		paint: {
			'circle-radius': 5,
			'circle-color': '#ffffff',
			'circle-stroke-color': '#4b3fb5',
			'circle-stroke-width': 2.5
		}
	});
	map.addLayer({
		id: HOVER,
		type: 'circle',
		source: HOVER,
		paint: {
			'circle-radius': 7,
			'circle-color': '#4b3fb5',
			'circle-stroke-color': '#ffffff',
			'circle-stroke-width': 3
		}
	});
}

const points = (pts: LngLat[]): GeoJSON.FeatureCollection => ({
	type: 'FeatureCollection',
	features: pts.map((p) => ({
		type: 'Feature',
		properties: {},
		geometry: { type: 'Point', coordinates: p }
	}))
});

/** The plain line through points, before the terrain under it is known. */
export function plainLine(pts: LngLat[]): GeoJSON.FeatureCollection {
	return pts.length < 2
		? EMPTY
		: {
				type: 'FeatureCollection',
				features: [
					{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: pts } }
				]
			};
}

/** Draw the measurement, or clear it (null). */
export function setMeasure(map: MlMap, d: MeasureDrawing | null) {
	if (!d && !map.getSource(LINE)) return;
	ensure(map);
	(map.getSource(LINE) as GeoJSONSource).setData(d?.line ?? EMPTY);
	(map.getSource(POINTS) as GeoJSONSource).setData(points(d?.points ?? []));
	(map.getSource(HOVER) as GeoJSONSource).setData(points(d?.hover ? [d.hover] : []));
	// Keep it on top of layers added since (weather pictures, zones).
	for (const id of ['measure-casing', LINE, POINTS, HOVER]) map.moveLayer(id);
}
