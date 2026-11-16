import { describe, expect, it } from 'vitest';
import { RAMPS } from '../radar';
import { colorize, fineLut, opacityAt, rampColor, rampTexels, type FineSpec } from './precipGl';

// As the server describes them (backend/snowwatch/maps/palette.py, fine_spec).
const SPEC: FineSpec = {
	from: 0.1,
	solid: 0.25,
	ramps: [
		{ type: 'snow', start: 1, steps: 36, top: 6 },
		{ type: 'mix', start: 37, steps: 20, top: 6 },
		{ type: 'rain', start: 57, steps: 72, top: 60 }
	]
};

describe('fine frames', () => {
	it('read each index as a type and a rate, as the server writes them', () => {
		const lut = fineLut(SPEC);
		const at = (i: number) => [lut[i * 2], lut[i * 2 + 1]];
		expect(at(0)).toEqual([0, 0]); // dry
		const step = (6 / 0.1) ** (1 / 36);
		expect(at(1)[0]).toBe(1);
		expect(at(1)[1]).toBeCloseTo(0.1 * Math.sqrt(step), 5);
		expect(at(36)[0]).toBe(1);
		expect(at(37)[0]).toBe(2);
		expect(at(57)[0]).toBe(3);
		expect(at(128)[1]).toBeCloseTo(60 / Math.sqrt((60 / 0.1) ** (1 / 72)), 3);
		expect(at(129)).toEqual([0, 0]);
	});

	it('colour along each ramp, through its stops, smoothly', () => {
		// At a stop, the stop's colour.
		expect(rampColor(RAMPS.rain, 2.5)).toEqual([0xf4, 0xd0, 0x3f]);
		expect(rampColor(RAMPS.snow, 0.01)).toEqual([0xc6, 0xdb, 0xef]);
		expect(rampColor(RAMPS.rain, 100)).toEqual([0xd7, 0x30, 0x1f]);
		// Between stops, no step bigger than a few levels from one texel to the next.
		const tex = rampTexels(SPEC, RAMPS);
		for (let row = 0; row < 3; row++)
			for (let x = 1; x < 256; x++)
				for (let c = 0; c < 3; c++) {
					const a = tex[(row * 256 + x - 1) * 4 + c];
					const b = tex[(row * 256 + x) * 4 + c];
					expect(Math.abs(a - b)).toBeLessThan(24);
				}
	});
});

describe("the layer's helpers", () => {
	it('work out an opacity by zoom, as the style would', () => {
		const expr = ['interpolate', ['linear'], ['zoom'], 10, 0.8, 12, 0.4, 13, 0] as never;
		expect(opacityAt(expr, 5)).toBe(0.8);
		expect(opacityAt(expr, 11)).toBeCloseTo(0.6);
		expect(opacityAt(expr, 12.5)).toBeCloseTo(0.2);
		expect(opacityAt(expr, 15)).toBe(0);
		expect(opacityAt(0.5, 3)).toBe(0.5);
	});

	it('colour a frame on the CPU for 3D, the hand-over mixed in as numbers', () => {
		// Four pixels: dry, light snow, heavy rain, and rain at the top of its ramp.
		const px = new Uint8ClampedArray([
			0, 0, 0, 255, 1, 1, 1, 255, 100, 100, 100, 255, 128, 128, 128, 255
		]);
		colorize(px, SPEC, RAMPS);
		expect(px[3]).toBe(0); // dry: clear
		expect(px[7]).toBeGreaterThan(140); // light snow: drawn, a little see-through
		expect(px[7]).toBeLessThan(255);
		expect(Array.from(px.slice(8, 12))).toEqual([
			...rampColor(RAMPS.rain, fineLut(SPEC)[201]),
			255
		]);
		expect(px[15]).toBe(255);
		// Half and half with dry: half the rate, still drawn; either way round.
		const a = new Uint8ClampedArray([100, 100, 100, 255]);
		colorize(a, SPEC, RAMPS, new Uint8ClampedArray([0, 0, 0, 255]), 0.5);
		expect(a[3]).toBe(255);
		const b = new Uint8ClampedArray([0, 0, 0, 255]);
		colorize(b, SPEC, RAMPS, new Uint8ClampedArray([100, 100, 100, 255]), 0.5);
		expect(b[3]).toBe(255);
	});
});
