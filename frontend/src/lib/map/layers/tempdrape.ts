// The temperature draped on the terrain: with the Temperature layer on and the map zoomed
// in, the ground is coloured by its height on the temperature layer's colours, from the
// temperature at sea level at the map's centre (for the frame on the slider) cooling at the
// layer's rate with height. The server's picture has a pixel every ~1.5–2 km (the mean of
// the ground under it); this follows every ridge and gully, and works in 3D. A MapLibre
// colour-relief layer on the elevation tiles, like the rain/snow line (snowline.ts).
import type { ExpressionSpecification, Map as MlMap } from 'maplibre-gl';
import { LAPSE_C_PER_M, TEMP } from '../weather';
import type { RampStep } from '../../radar';

export const TEMPDRAPE_ID = 'tempdrape';
/** From here in, the drape replaces the temperature picture. */
export const TEMPDRAPE_ZOOM = 10;
/** Above any ground in the box (and well above the coldest band at any sea-level value). */
const TOP_M = 9000;

/** The band a temperature falls in (the first holds anything colder). */
function bandOf(c: number, steps: RampStep[] = TEMP): RampStep {
	let out = steps[0];
	for (const s of steps) if (c >= s.from) out = s;
	return out;
}

/**
 * Colours by elevation for a temperature at sea level (°C): each band of the ramp from
 * where the temperature, cooling with height, enters it to where it leaves, with sharp
 * edges (half a metre) as the picture has.
 */
export function tempDrapeColors(
	seaC: number,
	lapsePerM = LAPSE_C_PER_M,
	steps: RampStep[] = TEMP
): ExpressionSpecification {
	const stops: (number | string)[] = [0, bandOf(seaC, steps).color];
	// Going up, the temperature falls through each band's lower bound in turn.
	for (let i = steps.length - 1; i > 0; i--) {
		const b = steps[i].from;
		const m = (seaC - b) / lapsePerM;
		if (m <= 1 || m >= TOP_M) continue;
		stops.push(m - 0.5, steps[i].color, m, steps[i - 1].color);
	}
	const last = stops[stops.length - 1] as string;
	stops.push(TOP_M, last);
	return ['interpolate', ['linear'], ['elevation'], ...stops] as unknown as ExpressionSpecification;
}

/** Show the drape for a temperature at sea level (°C), or hide it (null). */
export function setTempDrape(
	map: MlMap,
	seaC: number | null,
	beforeId?: string,
	lapsePerM = LAPSE_C_PER_M
): void {
	const have = !!map.getLayer(TEMPDRAPE_ID);
	if (seaC == null || !Number.isFinite(seaC)) {
		if (have) map.setLayoutProperty(TEMPDRAPE_ID, 'visibility', 'none');
		return;
	}
	if (!map.getSource('demshade')) return;
	const colors = tempDrapeColors(seaC, lapsePerM);
	if (!have) {
		map.addLayer(
			{
				id: TEMPDRAPE_ID,
				type: 'color-relief',
				source: 'demshade',
				minzoom: TEMPDRAPE_ZOOM - 0.5,
				paint: {
					'color-relief-color': colors,
					'color-relief-opacity': [
						'interpolate',
						['linear'],
						['zoom'],
						TEMPDRAPE_ZOOM - 0.5,
						0,
						TEMPDRAPE_ZOOM,
						0.6,
						14,
						0.45
					]
				}
			},
			beforeId && map.getLayer(beforeId) ? beforeId : undefined
		);
		return;
	}
	map.setPaintProperty(TEMPDRAPE_ID, 'color-relief-color', colors);
	map.setLayoutProperty(TEMPDRAPE_ID, 'visibility', 'visible');
}
