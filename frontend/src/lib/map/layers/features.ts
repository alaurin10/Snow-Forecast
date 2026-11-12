// Snow stations, field reports and ATES ratings on the map: one GeoJSON source each,
// added when first switched on and shown or hidden after that.
import type {
	ExpressionSpecification,
	GeoJSONSource,
	LayerSpecification,
	Map as MlMap
} from 'maplibre-gl';
import { ATES } from '../features';

export const STATION_LAYERS = ['stations', 'station-labels'];
export const REPORT_LAYERS = ['reports'];
export const ATES_LAYERS = ['ates-fill', 'ates-line'];
/** Layers a tap opens something for: a station's or a report's sheet. */
export const TAP_LAYERS = ['stations', 'reports'];

const vis = (on: boolean) => (on ? 'visible' : 'none') as 'visible' | 'none';

function source(map: MlMap, id: string, data: GeoJSON.FeatureCollection): boolean {
	const src = map.getSource(id) as GeoJSONSource | undefined;
	if (src) {
		src.setData(data);
		return false;
	}
	map.addSource(id, { type: 'geojson', data });
	return true;
}

function show(map: MlMap, ids: string[], on: boolean) {
	for (const id of ids) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis(on));
}

/** Station dots coloured by depth, labelled with the last 24 hours' new snow. */
export function setStations(
	map: MlMap,
	data: GeoJSON.FeatureCollection | null,
	on: boolean,
	halo: string
) {
	if (data && source(map, 'stations', data)) {
		map.addLayer({
			id: 'stations',
			type: 'circle',
			source: 'stations',
			minzoom: 5,
			paint: {
				'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 3.5, 10, 6.5],
				'circle-color': ['get', 'color'],
				'circle-stroke-color': ['case', ['get', 'fresh'], '#ffffff', 'rgba(255,255,255,0.7)'],
				'circle-stroke-width': ['case', ['get', 'fresh'], 2.2, 1.2]
			}
		});
		map.addLayer({
			id: 'station-labels',
			type: 'symbol',
			source: 'stations',
			minzoom: 7,
			filter: ['!=', ['get', 'label'], ''],
			layout: {
				'text-field': ['get', 'label'],
				'text-font': ['Open Sans Semibold'],
				'text-size': 11.5,
				'text-anchor': 'left',
				'text-offset': [0.75, 0],
				'text-optional': true
			},
			paint: { 'text-color': '#1f4fb0', 'text-halo-color': halo, 'text-halo-width': 1.6 }
		});
	}
	if (map.getLayer('station-labels'))
		map.setPaintProperty('station-labels', 'text-halo-color', halo);
	show(map, STATION_LAYERS, on);
}

/** Field reports as rings in the colour of their most telling kind. */
export function setReports(map: MlMap, data: GeoJSON.FeatureCollection | null, on: boolean) {
	if (data && source(map, 'reports', data)) {
		map.addLayer({
			id: 'reports',
			type: 'circle',
			source: 'reports',
			minzoom: 5,
			paint: {
				// Rings, so they don't read as stations.
				'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 3, 10, 5],
				'circle-color': '#ffffff',
				'circle-stroke-color': ['get', 'color'],
				'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 5, 2, 10, 3]
			}
		});
	}
	show(map, REPORT_LAYERS, on);
}

const atesColor = [
	'match',
	['get', 'rating'],
	...Object.entries(ATES).flatMap(([k, v]) => [k, v.color]),
	ATES.unrated.color
] as unknown as ExpressionSpecification;

/** ATES polygons and lines, as the owner's files rate them, under the labels. */
export function setAtes(
	map: MlMap,
	data: GeoJSON.FeatureCollection | null,
	on: boolean,
	beforeId?: string
) {
	if (data && source(map, 'ates', data)) {
		const layers: LayerSpecification[] = [
			{
				id: 'ates-fill',
				type: 'fill',
				source: 'ates',
				filter: ['==', ['geometry-type'], 'Polygon'],
				paint: {
					'fill-color': atesColor,
					'fill-opacity': ['interpolate', ['linear'], ['zoom'], 8, 0.45, 14, 0.28],
					'fill-outline-color': atesColor
				}
			},
			{
				id: 'ates-line',
				type: 'line',
				source: 'ates',
				layout: { 'line-cap': 'round', 'line-join': 'round' },
				paint: {
					'line-color': atesColor,
					// Zoom may only feed a top-level interpolate: the shape decides inside it.
					'line-width': [
						'interpolate',
						['linear'],
						['zoom'],
						9,
						['case', ['==', ['geometry-type'], 'LineString'], 2, 0.8],
						15,
						['case', ['==', ['geometry-type'], 'LineString'], 4, 0.8]
					],
					'line-dasharray': [
						'case',
						['==', ['get', 'rating'], 'unrated'],
						['literal', [2, 1.5]],
						['literal', [1, 0]]
					] as unknown as number[]
				}
			}
		];
		for (const l of layers)
			map.addLayer(l, beforeId && map.getLayer(beforeId) ? beforeId : undefined);
	}
	show(map, ATES_LAYERS, on);
}
