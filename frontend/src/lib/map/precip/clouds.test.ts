import { describe, expect, it } from 'vitest';
import { CLOUD_ADJUST_FROM, cloudAdjustAt } from './cloudlayer';
import { coverAt, HAS_HEIGHTS, HAS_TOPS, parseClouds } from './clouds';

/** A frame's inflated bytes as the server writes them (cloudheights.py). */
function frame(planes: number[][], w: number, h: number, flags: number, stepDm = 3): Uint8Array {
	const out = new Uint8Array(16 + planes.length * w * h);
	const v = new DataView(out.buffer);
	out.set([0x53, 0x57, 0x43, 0x31]); // "SWC1"
	v.setUint16(4, w, true);
	v.setUint16(6, h, true);
	out[8] = flags;
	out[9] = stepDm;
	v.setUint16(10, 4, true);
	planes.forEach((p, k) => {
		// Each row as the difference from the row above.
		const off = 16 + k * w * h;
		for (let i = 0; i < w * h; i++) out[off + i] = (p[i] - (i >= w ? p[i - w] : 0)) & 255;
	});
	return out;
}

describe('cloud frames', () => {
	it('reads the cover alone', () => {
		const p = parseClouds(frame([[10, 20, 30, 40]], 2, 2, 0))!;
		expect(p.width).toBe(2);
		expect(p.ds).toBe(4);
		expect([...p.shares].filter((_, i) => i % 4 === 0)).toEqual([10, 20, 30, 40]);
		expect([...p.heights]).toEqual([0, 0, 0, 0, 0, 0, 0, 0]);
	});

	it('reads heights and tops, interleaved for two textures', () => {
		const cover = [200, 200];
		const known = [255, 0];
		const low = [150, 0];
		const base = [50, 60];
		const top = [80, 90];
		const above = [25, 5];
		const p = parseClouds(
			frame([cover, known, low, base, top, above], 2, 1, HAS_HEIGHTS | HAS_TOPS)
		)!;
		expect(p.stepM).toBe(30);
		expect([...p.shares]).toEqual([200, 255, 150, 25, 200, 0, 0, 5]);
		expect([...p.heights]).toEqual([50, 80, 60, 90]);
	});

	it('marks the tops unknown when the frame has only bases', () => {
		const p = parseClouds(frame([[100], [255], [100], [70], [0]], 1, 1, HAS_HEIGHTS))!;
		expect([...p.heights]).toEqual([70, 255]);
	});

	it('refuses anything else', () => {
		expect(parseClouds(new Uint8Array(8))).toBeNull();
		const bad = frame([[1, 2]], 2, 1, 0);
		expect(parseClouds(bad.slice(0, bad.length - 1))).toBeNull();
		const step = frame([[1, 2]], 2, 1, 0);
		step[2] = 0x54; // "SWT1": a snow total step
		expect(parseClouds(step)).toBeNull();
	});
});

describe('the cloud against the terrain', () => {
	const deck = { cover: 100, above: 0, top: 2500 };

	it('covers everything below a full deck’s top, like a layer', () => {
		expect(coverAt(400, deck)).toBe(100); // a valley under it
		expect(coverAt(2000, deck)).toBe(100); // a ridge inside it
	});

	it('lets summits above the top show through, under only higher cloud', () => {
		expect(coverAt(3000, deck)).toBe(0);
		expect(coverAt(3000, { ...deck, above: 40 })).toBe(40);
		// Higher cloud never counts for more than the frame's cover.
		expect(coverAt(3000, { cover: 30, above: 60, top: 2500 })).toBe(30);
	});

	it('has a soft edge at the top', () => {
		const mid = coverAt(2500, deck);
		expect(mid).toBeGreaterThan(30);
		expect(mid).toBeLessThan(70);
	});

	it('keeps partial cover partial', () => {
		expect(coverAt(1000, { cover: 35, above: 0, top: 2500 })).toBe(35);
	});

	it('fades in the terrain view over a zoom level', () => {
		expect(cloudAdjustAt(CLOUD_ADJUST_FROM - 1)).toBe(0);
		expect(cloudAdjustAt(CLOUD_ADJUST_FROM)).toBeCloseTo(0.5);
		expect(cloudAdjustAt(CLOUD_ADJUST_FROM + 1)).toBe(1);
	});
});
