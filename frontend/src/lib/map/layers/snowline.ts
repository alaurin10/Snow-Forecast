// The rain/snow line draped on the terrain (docs/MAP-PLAN.md A5's "cheap extra"): with the
// Snow level layer on and the map zoomed in, terrain above the snow level at the map's
// centre (for the frame on the slider) is tinted white, and the ±150 m around it where
// rain and snow mix is tinted pink. A MapLibre colour-relief layer on the elevation tiles,
// so it follows every ridge and works in 3D.
import type { ExpressionSpecification, Map as MlMap } from 'maplibre-gl';

export const SNOWLINE_ID = 'snowline';
/** From here in, the drape replaces the coarse snow-level picture (which fades out by 15). */
export const SNOWLINE_ZOOM = 10;
/** Half the height of the band where rain and snow mix. */
export const MIX_M = 150;

/** Colours by elevation: clear below the mix band, pink across it, white above. */
export function snowLineColors(level: number): ExpressionSpecification {
	const lo = Math.max(1, level - MIX_M);
	const hi = lo + 2 * MIX_M;
	return [
		'interpolate',
		['linear'],
		['elevation'],
		lo - 0.5,
		'rgba(0, 0, 0, 0)',
		lo,
		'rgba(244, 166, 198, 0.75)',
		hi - 0.5,
		'rgba(244, 166, 198, 0.75)',
		hi,
		'rgba(240, 247, 255, 0.9)'
	] as unknown as ExpressionSpecification;
}

/** Show the drape for a snow level (metres above sea level), or hide it (null). */
export function setSnowLine(map: MlMap, level: number | null, beforeId?: string): void {
	const have = !!map.getLayer(SNOWLINE_ID);
	if (level == null) {
		if (have) map.setLayoutProperty(SNOWLINE_ID, 'visibility', 'none');
		return;
	}
	if (!map.getSource('demshade')) return;
	if (!have) {
		map.addLayer(
			{
				id: SNOWLINE_ID,
				type: 'color-relief',
				source: 'demshade',
				minzoom: SNOWLINE_ZOOM - 0.5,
				paint: {
					'color-relief-color': snowLineColors(level),
					'color-relief-opacity': [
						'interpolate',
						['linear'],
						['zoom'],
						SNOWLINE_ZOOM - 0.5,
						0,
						SNOWLINE_ZOOM,
						0.6
					]
				}
			},
			beforeId && map.getLayer(beforeId) ? beforeId : undefined
		);
		return;
	}
	map.setPaintProperty(SNOWLINE_ID, 'color-relief-color', snowLineColors(level));
	map.setLayoutProperty(SNOWLINE_ID, 'visibility', 'visible');
}
