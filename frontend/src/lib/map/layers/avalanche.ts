// Avalanche forecast zones on the map: each zone filled in the official colour of
// today's highest rating (grey when expired or not rated), its outline, and a bold
// outline round the zone whose bulletin the terrain layers are using.
import type { ExpressionSpecification, GeoJSONSource, Map as MlMap } from 'maplibre-gl';
import { DANGER_COLORS, NO_RATING_COLOR } from '../avalanche';

export const ZONES_SOURCE = 'avyzones';
export const ZONE_FILL = 'avyzones-fill';
export const ZONE_LINE = 'avyzones-line';
export const ZONE_FOCUS = 'avyzones-focus';

const fillColor: ExpressionSpecification = [
	'match',
	['get', 'level'],
	1,
	DANGER_COLORS[1],
	2,
	DANGER_COLORS[2],
	3,
	DANGER_COLORS[3],
	4,
	DANGER_COLORS[4],
	5,
	DANGER_COLORS[5],
	NO_RATING_COLOR
];

/**
 * Add the zones (once). The fill goes under the terrain overlays so they stay readable;
 * the lines go over everything but the labels.
 */
export function addZones(
	map: MlMap,
	data: GeoJSON.FeatureCollection,
	fillBefore: string | undefined,
	lineBefore: string | undefined
) {
	const src = map.getSource(ZONES_SOURCE) as GeoJSONSource | undefined;
	if (src) {
		src.setData(data);
		return;
	}
	map.addSource(ZONES_SOURCE, { type: 'geojson', data, tolerance: 0.6 });
	map.addLayer(
		{
			id: ZONE_FILL,
			type: 'fill',
			source: ZONES_SOURCE,
			layout: { visibility: 'none' },
			paint: {
				'fill-color': fillColor,
				// Strong when zoomed out, where zones are the point; faint up close, where
				// the terrain is.
				'fill-opacity': ['interpolate', ['linear'], ['zoom'], 5, 0.42, 9, 0.28, 12, 0.08]
			}
		},
		fillBefore
	);
	map.addLayer(
		{
			id: ZONE_LINE,
			type: 'line',
			source: ZONES_SOURCE,
			layout: { visibility: 'none', 'line-join': 'round' },
			paint: {
				'line-color': '#3b3646',
				'line-opacity': 0.7,
				'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.6, 10, 1.4]
			}
		},
		lineBefore
	);
	map.addLayer(
		{
			id: ZONE_FOCUS,
			type: 'line',
			source: ZONES_SOURCE,
			filter: ['==', ['get', 'id'], ''],
			layout: { visibility: 'none', 'line-join': 'round' },
			paint: {
				'line-color': '#ffffff',
				'line-width': 3,
				'line-dasharray': [2, 1.2]
			}
		},
		lineBefore
	);
}

const vis = (on: boolean) => (on ? 'visible' : 'none');

/** Show the zones or not, and outline the one in use (null: none). */
export function setZones(map: MlMap, show: boolean, focus: string | null, dark: boolean) {
	if (!map.getLayer(ZONE_FILL)) return;
	map.setLayoutProperty(ZONE_FILL, 'visibility', vis(show));
	map.setLayoutProperty(ZONE_LINE, 'visibility', vis(show));
	map.setPaintProperty(ZONE_LINE, 'line-color', dark ? '#e8e4f0' : '#3b3646');
	map.setLayoutProperty(ZONE_FOCUS, 'visibility', vis(focus != null));
	map.setFilter(ZONE_FOCUS, ['==', ['get', 'id'], focus ?? '']);
	map.setPaintProperty(ZONE_FOCUS, 'line-color', dark ? '#ffffff' : '#1f1b2e');
}
