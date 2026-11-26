// The Temperature layer: its key, bringing a sea-level temperature to a height, its
// continuous slider, and its smooth colours.
import { describe, expect, it } from 'vitest';
import { levelLut, tempColor, tempLut } from './precip/totalgl';
import { LEVEL_MIN, LEVEL_STEP } from './precip/steps';
import {
	freezingHeightAt,
	hoursAt,
	snowlineKind,
	valueAt,
	layerName,
	posAt,
	tempLabel,
	tempSlider,
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

	it('finds where the colours cross 32 °F, between frames as the map blends them', () => {
		const temps = [
			{ t: 0, sea_c: 13 },
			{ t: 3 * 3600, sea_c: 19.5 },
			{ t: 6 * 3600, sea_c: null }
		];
		expect(freezingHeightAt(temps, 0)).toBeCloseTo(2000);
		expect(freezingHeightAt(temps, 1.5 * 3600)).toBeCloseTo(2500); // halfway: 16.25 °C
		expect(freezingHeightAt(temps, 9 * 3600)).toBeCloseTo(3000); // past the last number
		expect(tempAt(16.25, freezingHeightAt(temps, 1.5 * 3600)!)).toBeCloseTo(0);
		expect(freezingHeightAt([{ t: 0, sea_c: -2 }], 0)).toBe(0); // freezing to sea level
		expect(freezingHeightAt([{ t: 0, sea_c: 10 }], 0, 5)).toBeCloseTo(2000);
		expect(freezingHeightAt([{ t: 0, sea_c: null }], 0)).toBeNull();
	});
});

describe('temperature slider', () => {
	const H = 3600;
	const now = 1_800_000_000;
	// Every 3 h for 84 h, then every 6 h to 240 h, the first an hour ahead.
	const hours = [
		...Array.from({ length: 28 }, (_, i) => 1 + 3 * i),
		...Array.from({ length: 26 }, (_, i) => 88 + 6 * i)
	];
	const frames = hours.map((h) => ({ t: now + h * H }));

	it('marks the first days finely and the far ones coarsely', () => {
		const s = tempSlider(frames, now)!;
		expect(s.t0).toBe(now + H);
		expect(s.ticks).toEqual(['Now', '12h', '1d', '2d', '3d', '5d', '7d', '10d']);
		// Hours from the first frame (an hour ahead of now).
		expect(s.marks).toEqual([0, 11, 23, 47, 71, 119, 167, 237]);
		expect(s.hours[0]).toBe(0);
		// Evenly spaced marks: the first day takes two of seven stretches of the slider.
		expect(posAt(23, s.marks)).toBe(2);
		expect(hoursAt(6.5, s.marks)).toBeCloseTo(202);
		expect(tempSlider(frames.slice(0, 1), now)).toBeNull();
	});

	it('says when a time on the slider is', () => {
		const l = tempLabel(now + 26 * H + 1300, now * 1000);
		expect(l.rel).toBe('forecast · in 26 h');
		expect(l.when).not.toMatch(/:/); // to the hour
	});
});

describe('temperature colours', () => {
	const color = (c: number) => tempColor(c);
	const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

	it("run smoothly between the key's colours", () => {
		// Each band's colour sits at its middle; between two middles, part way.
		expect(color(5)).toEqual(hex(TEMP.find((s) => s.from === 4)!.color));
		const mid = color(6);
		const a = hex(TEMP.find((s) => s.from === 4)!.color);
		const b = hex(TEMP.find((s) => s.from === 6)!.color);
		mid.forEach((v, k) => expect(v).toBe(Math.round((a[k] + b[k]) / 2)));
	});

	it('break sharply at 0 °C, and hold at the ends', () => {
		expect(color(-0.01)).toEqual(hex(TEMP.find((s) => s.from === -2)!.color));
		expect(color(0)).toEqual(hex(TEMP.find((s) => s.from === 0)!.color));
		expect(color(-60)).toEqual(hex(TEMP[0].color));
		expect(color(45)).toEqual(hex(TEMP[TEMP.length - 1].color));
	});

	it('fill the codes the numbers use', () => {
		const lut = tempLut();
		expect(Array.from(lut.slice(0, 4))).toEqual([0, 0, 0, 0]); // no data: clear
		// Code 141 is 0 °C (−70 + 140 × 0.5).
		expect(Array.from(lut.slice(141 * 4, 141 * 4 + 3))).toEqual(color(0));
		expect(lut[255 * 4 + 3]).toBe(255);
	});
});

describe('the snow level as rain, mix or snow', () => {
	it('reads a point between frames as the map blends them', () => {
		const at = [
			{ t: 0, value: 1000 },
			{ t: 3 * 3600, value: 1600 },
			{ t: 6 * 3600, value: null }
		];
		expect(valueAt(at, 3600)).toBeCloseTo(1200);
		expect(valueAt(at, -5)).toBe(1000);
		expect(valueAt(at, 9 * 3600)).toBe(1600);
		expect(valueAt([], 0)).toBeNull();
	});

	it('mixes within 150 m of the snow level, snow above, rain below', () => {
		expect(snowlineKind(-151).kind).toBe('rain');
		expect(snowlineKind(-150).kind).toBe('mix');
		expect(snowlineKind(149).kind).toBe('mix');
		expect(snowlineKind(150).kind).toBe('snow');
	});

	it('colours whole codes with the mix band edges between two of them', () => {
		const lut = levelLut();
		const kindAt = (m: number) => {
			const c = Math.round(1 + (m - LEVEL_MIN) / LEVEL_STEP);
			return lut.slice(c * 4, c * 4 + 4).join(',');
		};
		const rain = '159,212,154,140';
		const mix = '224,69,123,255';
		const snow = '44,95,184,255';
		expect([kindAt(-160), kindAt(-140), kindAt(140), kindAt(160)]).toEqual([rain, mix, mix, snow]);
		expect(lut.slice(0, 4).join(',')).toBe('0,0,0,0'); // code 0: no data
	});
});
