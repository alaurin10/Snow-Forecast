// The Temperature layer: its key, bringing a sea-level temperature to a height, its
// continuous slider, and its smooth colours.
import { describe, expect, it } from 'vitest';
import { tempColor, tempLut } from './precip/totalgl';
import {
	hoursAt,
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
