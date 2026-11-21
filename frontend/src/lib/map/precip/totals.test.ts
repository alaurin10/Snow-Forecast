// The snow total drawn from numbers: the step format against the server's own encoder, the
// colours against the legend, and the layer's choice of steps and elevation tiles. (The
// drawing itself is checked in a real browser: e2e/layers.spec.ts.)
import { readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { TOTAL } from '../../radar';
import { cmCode, codeCm, parseStep } from './steps';
import { FIRST_CODE, totalLut } from './totalgl';
import { adjustAt, ADJUST_FROM, bracketHours, elevationFor } from './totallayer';
import { hoursAt, posAt, totalMarks, totalWords } from '../weather';

const dir = new URL('./__fixtures__/', import.meta.url);

describe('steps', () => {
	it("reads the server's steps exactly", () => {
		const want = JSON.parse(readFileSync(new URL('step.json', dir), 'utf8')) as {
			area: number[][];
			bands: number[][][];
			band_m: number;
		};
		const p = parseStep(new Uint8Array(gunzipSync(readFileSync(new URL('step.bin', dir)))))!;
		expect(p).not.toBeNull();
		expect([p.areaWidth, p.areaHeight, p.bandWidth, p.bandHeight, p.bandCount, p.bandM]).toEqual([
			30, 20, 15, 10, 10, 500
		]);
		expect([...p.area]).toEqual(want.area.flat());
		expect([...p.bands]).toEqual(want.bands.flat(2));
		// Band 3 is 1,500 m: 15 cm there.
		expect(codeCm(p.bands[3 * 150])).toBeCloseTo(15, 0);
	});

	it('turns down anything else', () => {
		expect(parseStep(new Uint8Array(20))).toBeNull();
		const raw = new Uint8Array(gunzipSync(readFileSync(new URL('step.bin', dir))));
		expect(parseStep(raw.slice(0, raw.length - 1))).toBeNull();
	});

	it('codes depths on the same scale as the server', () => {
		expect(codeCm(0)).toBe(0);
		expect(cmCode(0.1)).toBe(0);
		for (const cm of [0.5, 2.54, 30, 500]) expect(codeCm(cmCode(cm))).toBeCloseTo(cm, 4);
	});

	it("colours each depth as the legend's cells do, and nothing under an inch", () => {
		const lut = totalLut();
		const at = (cm: number) => [
			...lut.slice(Math.ceil(cmCode(cm)) * 4, Math.ceil(cmCode(cm)) * 4 + 4)
		];
		expect(at(1)[3]).toBe(0);
		const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
		expect(at(10)).toEqual([...hex(TOTAL[1].color), 255]);
		expect(at(200)).toEqual([...hex(TOTAL[8].color), 255]);
		expect(codeCm(FIRST_CODE)).toBeCloseTo(TOTAL[0].from, 4);
	});
});

describe('the snow total layer', () => {
	it('mixes the steps either side of the slider, from nothing before the first', () => {
		const hours = [6, 12, 24, 48];
		expect(bracketHours(3, hours)).toEqual({ a: -1, b: 0, f: 0.5 });
		expect(bracketHours(18, hours)).toEqual({ a: 1, b: 2, f: 0.5 });
		expect(bracketHours(12, hours)).toEqual({ a: 1, b: 2, f: 0 });
		expect(bracketHours(100, hours)).toEqual({ a: 3, b: 3, f: 0 });
		expect(bracketHours(5, [])).toEqual({ a: -1, b: -1, f: 0 });
		// A value at an instant (the temperature) shows the first step before it, not nothing.
		expect(bracketHours(3, hours, false)).toEqual({ a: 0, b: 0, f: 0 });
		expect(bracketHours(18, hours, false)).toEqual({ a: 1, b: 2, f: 0.5 });
	});

	it('adjusts to terrain from zoom 8, faded in over a zoom level', () => {
		expect(adjustAt(ADJUST_FROM - 1)).toBe(0);
		expect(adjustAt(ADJUST_FROM)).toBeCloseTo(0.5);
		expect(adjustAt(ADJUST_FROM + 1)).toBe(1);
	});

	it("reads a fine map tile's elevation from its ancestor at zoom 13", () => {
		expect(elevationFor(10, 5, 6)).toEqual({ z: 10, x: 5, y: 6, at: [0, 0, 1] });
		expect(elevationFor(15, 4 * 100 + 3, 4 * 200 + 1)).toEqual({
			z: 13,
			x: 100,
			y: 200,
			at: [0.75, 0.25, 0.25]
		});
	});
});

describe('the continuous slider', () => {
	it('spaces the windows evenly and slides between them', () => {
		const marks = totalMarks([6, 12, 18, 24, 48, 72, 120, 168, 240]);
		expect(marks).toEqual([12, 24, 48, 72, 120, 168, 240]);
		expect(hoursAt(0.5, marks)).toBe(18);
		expect(hoursAt(5.5, marks)).toBe(204);
		expect(posAt(204, marks)).toBe(5.5);
		expect(posAt(1, marks)).toBe(0);
		// Models that stop short: the slider ends where they do.
		expect(totalMarks([6, 12, 24, 48, 60, 66])).toEqual([12, 24, 48, 66]);
	});

	it('says how long in words', () => {
		expect(totalWords(18)).toBe('Next 18 hours');
		expect(totalWords(60)).toBe('Next 2½ days');
		expect(totalWords(240)).toBe('Next 10 days');
	});
});
