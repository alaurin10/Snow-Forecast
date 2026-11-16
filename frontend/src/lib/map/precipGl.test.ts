import { describe, expect, it } from 'vitest';
import { RAMPS } from '../radar';
import { fineLut, rampColor, rampTexels, type FineSpec } from './precipGl';

// As the server describes them (backend/snowwatch/maps/palette.py, fine_spec).
const SPEC: FineSpec = {
	from: 0.03,
	solid: 0.15,
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
		const step = (6 / 0.03) ** (1 / 36);
		expect(at(1)[0]).toBe(1);
		expect(at(1)[1]).toBeCloseTo(0.03 * Math.sqrt(step), 5);
		expect(at(36)[0]).toBe(1);
		expect(at(37)[0]).toBe(2);
		expect(at(57)[0]).toBe(3);
		expect(at(128)[1]).toBeCloseTo(60 / Math.sqrt((60 / 0.03) ** (1 / 72)), 3);
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
