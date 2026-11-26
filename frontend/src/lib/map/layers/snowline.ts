// The rain/snow line draped on the terrain (docs/MAP-PLAN.md A5's "cheap extra"): with the
// Snow level layer on and the map zoomed in, terrain is tinted as rain, mix or snow by its
// height against the snow level at the map's centre (for the frame on the slider), in the
// layer's colours (SNOWLINE_KINDS). A MapLibre colour-relief layer on the elevation tiles,
// so it follows every ridge and works in 3D. It stands in for the layer drawn from numbers
// (which gives each spot its own snow level) only where those aren't there.
import type { ExpressionSpecification, Map as MlMap } from 'maplibre-gl';
import { MIX_BAND_M, SNOWLINE_KINDS } from '../weather';

export const SNOWLINE_ID = 'snowline';
/** From here in, the drape replaces the coarse snow-level picture (which fades out by 15). */
export const SNOWLINE_ZOOM = 10;
/** Half the height of the band where rain and snow mix. */
export const MIX_M = MIX_BAND_M;

const rgba = (k: (typeof SNOWLINE_KINDS)[number]) => {
	const [r, g, b] = [1, 3, 5].map((i) => parseInt(k.color.slice(i, i + 2), 16));
	return `rgba(${r}, ${g}, ${b}, ${k.alpha})`;
};

/** Colours by elevation: rain below the mix band, mix across it, snow above. */
export function snowLineColors(level: number): ExpressionSpecification {
	const lo = Math.max(1, level - MIX_M);
	const hi = lo + 2 * MIX_M;
	const [rain, mix, snow] = SNOWLINE_KINDS.map(rgba);
	return [
		'interpolate',
		['linear'],
		['elevation'],
		lo - 0.5,
		rain,
		lo,
		mix,
		hi - 0.5,
		mix,
		hi,
		snow
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
