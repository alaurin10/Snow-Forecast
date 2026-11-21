// The Temperature layer: its key, bringing a sea-level temperature to a height, and the
// drape that colours the terrain by height zoomed in.
import { describe, expect, it } from 'vitest';
import { tempDrapeColors } from './layers/tempdrape';
import {
	layerName,
	layerSource,
	TEMP,
	tempAt,
	tempTick,
	WEATHER_CHOICES,
	WEATHER_WORDS,
	weatherView
} from './weather';
import { MAP_WEATHER } from '../prefs.svelte';
import type { Frame, Timeline } from '../radar';

describe('temperature layer', () => {
	it('is a choice, shown as a loop of its own frames', () => {
		expect(MAP_WEATHER).toContain('temp');
		expect(WEATHER_CHOICES.map((c) => c.id)).toContain('temp');
		expect(WEATHER_WORDS.temp).toBe('the temperature');
		expect(layerName('temp', 'gust')).toBe('temp');
		const f = { t: 100, file: 'tt100-a.png', key: 'k', kind: 'forecast', span_h: 0, hours: 0 };
		const tl = {
			layers: { temp: [{ ...f, src: { north: 'hrdps', south: 'nbm' }, runs: {} }] }
		} as unknown as Timeline;
		const v = weatherView(tl, 'temp', 'gust');
		expect(v.mode).toBe('loop');
		expect(v.frames.map((x) => x.file)).toEqual(['tt100-a.png']);
		expect(layerSource('temp', 'gust', v.frames[0] as Frame)).toMatch(
			/Canadian HRDPS in Canada, NOAA's National Blend of Models in the US.*6\.5 °C a kilometre/
		);
	});

	it('keys every 10 °C, in either unit', () => {
		expect(TEMP.map((s) => tempTick(s.from, 'metric')).filter(Boolean)).toEqual([
			'-30',
			'-20',
			'-10',
			'0',
			'10',
			'20',
			'30'
		]);
		expect(tempTick(0, 'imperial')).toBe('32');
		expect(tempTick(-10, 'imperial')).toBe('14');
		expect(tempTick(-8, 'metric')).toBe('');
	});

	it('cools 6.5 °C a kilometre from sea level', () => {
		expect(tempAt(5, 2000)).toBeCloseTo(-8);
		expect(tempAt(5, 0)).toBe(5);
		expect(tempAt(5, -50)).toBe(5); // below sea level: as the sea
		expect(tempAt(5, 1000, 5)).toBeCloseTo(0);
	});
});

describe('temperature drape', () => {
	it("colours each height on the layer's bands", () => {
		const e = tempDrapeColors(3) as unknown as (string | number)[];
		expect(e.slice(0, 3)).toEqual(['interpolate', ['linear'], ['elevation']]);
		const stops = e.slice(3);
		// Sea level: 3 °C is in the 2 °C band.
		expect(stops.slice(0, 2)).toEqual([0, TEMP.find((s) => s.from === 2)!.color]);
		// 0 °C is reached at 3 / 0.0065 ≈ 461.5 m: green below, ice blue above.
		const ice = stops.indexOf(TEMP.find((s) => s.from === -2)!.color);
		expect(stops[ice - 1]).toBeCloseTo(3 / 0.0065, 1);
		expect(stops[ice - 2]).toBe(TEMP.find((s) => s.from === 0)!.color);
		expect(stops[ice - 3]).toBeCloseTo(3 / 0.0065 - 0.5, 1);
		// Heights only rise, and the top holds the coldest band reached.
		const heights = stops.filter((_, i) => i % 2 === 0) as number[];
		expect(heights).toEqual([...heights].sort((a, b) => a - b));
		expect(stops[stops.length - 1]).toBe(TEMP[0].color);
	});

	it('is one colour where no band edge is within reach', () => {
		const e = tempDrapeColors(-40) as unknown as (string | number)[];
		expect(e.slice(3)).toEqual([0, TEMP[0].color, 9000, TEMP[0].color]);
	});
});
