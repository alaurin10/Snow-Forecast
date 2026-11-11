// The terrain engine: Terrarium decoding, gap-filling, tile borders, slope and aspect.
import { describe, expect, it } from 'vitest';
import {
	bordered,
	DemCache,
	decodeTerrarium,
	encodeTerrarium,
	locate,
	metresPerPixel,
	sample,
	stitch,
	tileLat,
	upsample,
	type Pixels
} from './dem';
import { hornAt, paint, sectorOf, slopeClass, SLOPE_CLASSES, type Sector } from './analysis';
import { matchQuery, parseMatch } from './client';

const SIZE = 8;

/** A tile whose elevation is f(row, col). */
function tile(f: (r: number, c: number) => number, size = SIZE): Float32Array {
	const out = new Float32Array(size * size);
	for (let r = 0; r < size; r++) for (let c = 0; c < size; c++) out[r * size + c] = f(r, c);
	return out;
}

/** Elevations with a one-pixel border, rising `deg` degrees toward the east or north. */
function plane(deg: number, toward: 'east' | 'north', m: number, size = SIZE) {
	const rise = Math.tan((deg * Math.PI) / 180) * m;
	return tile((r, c) => 1000 + (toward === 'east' ? c * rise : -r * rise), size + 2);
}

describe('Terrarium encoding', () => {
	it('round-trips elevations to 1/256 m', () => {
		const e = Float32Array.from([-412.5, 0, 1234.25, 4421.75, 8848]);
		const px: Pixels = { data: encodeTerrarium(e), width: 5, height: 1 };
		const back = decodeTerrarium(px);
		e.forEach((v, i) => expect(back[i]).toBeCloseTo(v, 2));
	});

	it('decodes sea level as 128, 0, 0', () => {
		const px: Pixels = { data: Uint8ClampedArray.from([128, 0, 0, 255]), width: 1, height: 1 };
		expect(decodeTerrarium(px)[0]).toBe(0);
	});
});

describe('filling a tile from its parent', () => {
	it('keeps a smooth ramp smooth and in the right quarter', () => {
		const parent = tile((_, c) => c * 10);
		// The east half, one zoom down: the parent's columns 4–8 spread over 8 pixels.
		const child = upsample(parent, SIZE, 1, 0);
		expect(child[3]).toBeCloseTo(parent[5] + 2.5, 5);
		// Monotonic across the row.
		for (let c = 1; c < SIZE - 1; c++) expect(child[c]).toBeGreaterThan(child[c - 1]);
		expect(child[0]).toBeGreaterThanOrEqual(35);
		expect(child[SIZE - 1]).toBeLessThanOrEqual(70);
	});

	it('stitches four quarter tiles in reading order', () => {
		const q = [1, 2, 3, 4].map((v) => tile(() => v, 2));
		const s = stitch(q, 2);
		expect(Array.from(s)).toEqual([1, 1, 2, 2, 1, 1, 2, 2, 3, 3, 4, 4, 3, 3, 4, 4]);
	});
});

describe('tile borders', () => {
	it('takes each edge from the neighbour on that side', () => {
		const around = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((v) => tile(() => v, 3));
		const g = bordered(around, 3);
		const at = (r: number, c: number) => g[r * 5 + c];
		expect(at(0, 0)).toBe(0);
		expect(at(0, 2)).toBe(1);
		expect(at(0, 4)).toBe(2);
		expect(at(2, 0)).toBe(3);
		expect(at(2, 2)).toBe(4);
		expect(at(2, 4)).toBe(5);
		expect(at(4, 2)).toBe(7);
		expect(at(4, 4)).toBe(8);
	});

	it('repeats its own edge where a neighbour is missing', () => {
		const mid = tile((r, c) => r * 10 + c, 3);
		const g = bordered([null, null, null, null, mid, null, null, null, null], 3);
		expect(g[0 * 5 + 2]).toBe(mid[1]); // north border = own top row
		expect(g[4 * 5 + 4]).toBe(mid[8]); // south-east corner = own corner
	});
});

describe('geometry', () => {
	it('puts Whistler in the tile Mapterhorn names', () => {
		const t = locate(50.06, -122.95, 12);
		expect([t.x, t.y]).toEqual([649, 1388]);
	});

	it('knows a zoom-12 pixel is about 12 m at 50°N', () => {
		expect(metresPerPixel(50, 12)).toBeCloseTo(12.3, 1);
		expect(tileLat(0, 0)).toBeCloseTo(85.05, 1);
	});

	it('samples between pixel centres', () => {
		const e = tile((_, c) => c * 2, 4);
		expect(sample(e, 4, 1.0, 2)).toBeCloseTo(1, 5);
	});
});

describe('slope and aspect (Horn)', () => {
	it('measures a 30° plane rising east as 30°, facing west', () => {
		const g = plane(30, 'east', 10);
		const { slope, aspect } = hornAt(g, SIZE + 2, 4, 4, 10, 10);
		expect(slope).toBeCloseTo(30, 3);
		expect(aspect).toBeCloseTo(270, 3);
		expect(sectorOf(aspect)).toBe('W');
	});

	it('measures a 38° plane rising north as facing south', () => {
		const g = plane(38, 'north', 12);
		const { slope, aspect } = hornAt(g, SIZE + 2, 4, 4, 12, 12);
		expect(slope).toBeCloseTo(38, 3);
		expect(aspect).toBeCloseTo(180, 3);
	});

	it('sorts slopes into the drawn classes by whole degree', () => {
		expect(slopeClass(24.9)).toBe(-1);
		expect(SLOPE_CLASSES[slopeClass(29.9)].from).toBe(25);
		expect(SLOPE_CLASSES[slopeClass(35)].from).toBe(35);
		expect(SLOPE_CLASSES[slopeClass(45.9)].from).toBe(40);
		expect(SLOPE_CLASSES[slopeClass(60)].from).toBe(51);
	});

	it('paints a steep tile and leaves a gentle one clear', () => {
		const m = metresPerPixel(tileLat(1388.5, 12), 12, SIZE);
		const steep = paint('slope', plane(37, 'east', m), SIZE, 12, 1388);
		expect(steep).not.toBeNull();
		// Red (35–39°), opaque.
		expect(Array.from(steep!.slice(0, 4))).toEqual([0xe2, 0x40, 0x2b, 255]);
		expect(paint('slope', plane(10, 'east', m), SIZE, 12, 1388)).toBeNull();
	});

	it('matches only the listed aspects, steep enough and in the band', () => {
		const m = metresPerPixel(tileLat(1388.5, 12), 12, SIZE);
		const westFacing = plane(35, 'east', m);
		const rule = (aspects: Sector[], ranges: [number, number][] = []) => ({
			slopeMin: 30,
			rules: [{ aspects, ranges }]
		});
		expect(paint('match', westFacing, SIZE, 12, 1388, rule(['W', 'NW']))).not.toBeNull();
		expect(paint('match', westFacing, SIZE, 12, 1388, rule(['E']))).toBeNull();
		// The plane rises from 1000 m: a band below it misses, a second band over it hits.
		expect(paint('match', westFacing, SIZE, 12, 1388, rule(['W'], [[500, 900]]))).toBeNull();
		expect(
			paint(
				'match',
				westFacing,
				SIZE,
				12,
				1388,
				rule(
					['W'],
					[
						[500, 900],
						[900, 2000]
					]
				)
			)
		).not.toBeNull();
		expect(
			paint('match', westFacing, SIZE, 12, 1388, { slopeMin: 40, rules: rule(['W']).rules })
		).toBeNull();
		// Any rule may match.
		const two = { slopeMin: 30, rules: [...rule(['E']).rules, ...rule(['W']).rules] };
		expect(paint('match', westFacing, SIZE, 12, 1388, two)).not.toBeNull();
	});

	it('carries match settings through a tile URL', () => {
		const m = {
			slopeMin: 35,
			rules: [
				{ aspects: ['N', 'NE'] as Sector[], ranges: [[1800, 9000]] as [number, number][] },
				{
					aspects: ['S'] as Sector[],
					ranges: [
						[-500, 1500],
						[1900, 9000]
					] as [number, number][]
				},
				{ aspects: ['W'] as Sector[], ranges: [] }
			]
		};
		expect(parseMatch(matchQuery(m))).toEqual(m);
		expect(parseMatch('')).toBeUndefined();
	});
});

describe('fetching elevation', () => {
	// A fake upstream: each tile's "file" is its own URL, decoded to a flat tile whose
	// height says which zoom it came from.
	const decode = async (blob: Blob): Promise<Pixels> => {
		const url = await blob.text();
		const z = Number(/\/(\d+)\/\d+\/\d+\.\w+$/.exec(url)![1]);
		const e = new Float32Array(SIZE * SIZE).fill(z * 100);
		return { data: encodeTerrarium(e), width: SIZE, height: SIZE };
	};
	function upstream(status: (url: string) => number | 'error') {
		const seen: string[] = [];
		const f = (async (input: RequestInfo | URL) => {
			const url = String(input);
			seen.push(url);
			const s = status(url);
			if (s === 'error') throw new TypeError('network');
			return new Response(s === 200 ? url : 'no', { status: s });
		}) as typeof fetch;
		return { f, seen };
	}

	it('uses the tile when Mapterhorn has it', async () => {
		const { f, seen } = upstream(() => 200);
		const dem = new DemCache({ decode, fetch: f });
		const e = await dem.elev(13, 10, 20);
		expect(e.srcZ).toBe(13);
		expect(e.data[0]).toBeCloseTo(1300, 2);
		expect(seen).toEqual(['https://tiles.mapterhorn.com/13/10/20.webp']);
		// Cached: no second fetch.
		await dem.elev(13, 10, 20);
		expect(seen.length).toBe(1);
	});

	it('fills a tile finer than the area has from its parent', async () => {
		const { f } = upstream((u) => (u.includes('/15/') || u.includes('/14/') ? 404 : 200));
		const dem = new DemCache({ decode, fetch: f });
		const e = await dem.elev(15, 4, 4);
		expect(e.srcZ).toBe(13);
		expect(e.data[5]).toBeCloseTo(1300, 2);
		// For MapLibre it becomes numbers to encode rather than the original file.
		const t = await dem.demTile(15, 4, 4);
		expect('bytes' in t).toBe(false);
	});

	it('treats a missing tile at zoom 12 or below as open water', async () => {
		const { f, seen } = upstream(() => 404);
		const dem = new DemCache({ decode, fetch: f });
		const e = await dem.elev(10, 1, 1);
		expect(e.sea).toBe(true);
		expect(e.data.every((v) => v === 0)).toBe(true);
		expect(seen.length).toBe(1);
	});

	it('switches to the AWS tiles after repeated network failures', async () => {
		const { f, seen } = upstream((u) => (u.includes('mapterhorn') ? 'error' : 200));
		const dem = new DemCache({ decode, fetch: f });
		for (let i = 0; i < 4; i++) await dem.elev(12, i, 0).catch(() => null);
		expect(dem.fallback).toBe(true);
		const e = await dem.elev(12, 9, 9);
		// Four AWS tiles one zoom deeper, stitched.
		expect(e.size).toBe(SIZE * 2);
		expect(e.data[0]).toBeCloseTo(1300, 2);
		expect(
			seen.some((u) => u.startsWith('https://s3.amazonaws.com/') && u.includes('/13/18/18.png'))
		).toBe(true);
	});

	it("doesn't give up on Mapterhorn while the device is offline", async () => {
		const { f } = upstream(() => 'error');
		const dem = new DemCache({ decode, fetch: f, online: () => false });
		for (let i = 0; i < 6; i++) await dem.elev(12, i, 0).catch(() => null);
		expect(dem.fallback).toBe(false);
	});
});
