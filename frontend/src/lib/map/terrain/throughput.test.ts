// The terrain worker's throughput work (performance pass, PR 4): downloads called off,
// slope and aspect kept and recoloured, the concern class without the factors, the match
// query in one form, job rectangles snapped, and the wind effect yielding between rays.
import { describe, expect, it } from 'vitest';
import {
	classify,
	hornAt,
	matches,
	paint,
	paintClasses,
	slopeClass,
	unborder,
	SECTORS,
	FLAT_DEG,
	type MatchParams,
	type TerrainMode
} from './analysis';
import { concernAt, concernCls, type ConcernInputs, type ConcernParams } from './concern';
import { DemCache, encodeTerrarium, metresPerPixel, tileLat, type Pixels } from './dem';
import { contains, snap, type Grid } from './grid';
import { matchQuery, parseMatch } from './client';
import { windEffect } from './wind';

const SIZE = 8;

describe('calling off elevation downloads', () => {
	const decode = async (): Promise<Pixels> => ({
		data: encodeTerrarium(new Float32Array(SIZE * SIZE).fill(1200)),
		width: SIZE,
		height: SIZE
	});
	/** An upstream whose answers wait until `release()`, and which notes aborts. */
	function slow() {
		const calls: { url: string; signal?: AbortSignal | null }[] = [];
		let release = () => {};
		const gate = new Promise<void>((r) => (release = r));
		const f = (async (input: RequestInfo | URL, init?: RequestInit) => {
			const signal = init?.signal;
			calls.push({ url: String(input), signal });
			await new Promise<void>((resolve, reject) => {
				gate.then(resolve);
				signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
			});
			return new Response('x', { status: 200 });
		}) as typeof fetch;
		return { f, calls, release: () => release() };
	}

	it('stops a download only when everyone waiting has called it off', async () => {
		const up = slow();
		const dem = new DemCache({ decode, fetch: up.f });
		const a = new AbortController();
		const b = new AbortController();
		const pa = dem.elev(13, 1, 1, a.signal);
		const pb = dem.elev(13, 1, 1, b.signal);
		await Promise.resolve();
		expect(up.calls).toHaveLength(1);
		a.abort();
		await expect(pa).rejects.toThrow('Aborted');
		expect(up.calls[0].signal?.aborted).toBe(false);
		b.abort();
		await expect(pb).rejects.toThrow('Aborted');
		expect(up.calls[0].signal?.aborted).toBe(true);
		// Nothing was kept, and it wasn't a failure: asking again downloads it.
		up.release();
		const again = await dem.elev(13, 1, 1);
		expect(again.data[0]).toBeCloseTo(1200, 2);
		expect(up.calls).toHaveLength(2);
		expect(dem.fallback).toBe(false);
	});

	it('keeps going for someone who asked without a way to call it off', async () => {
		const up = slow();
		const dem = new DemCache({ decode, fetch: up.f });
		const a = new AbortController();
		const pa = dem.elev(13, 2, 2, a.signal);
		const keep = dem.elev(13, 2, 2);
		a.abort();
		await expect(pa).rejects.toThrow('Aborted');
		expect(up.calls[0].signal?.aborted).toBe(false);
		up.release();
		expect((await keep).srcZ).toBe(13);
	});

	it('many cancelled requests in a row never switch to the fallback tiles', async () => {
		const up = slow();
		const dem = new DemCache({ decode, fetch: up.f });
		for (let i = 0; i < 6; i++) {
			const c = new AbortController();
			const p = dem.elev(12, i, 0, c.signal);
			c.abort();
			await expect(p).rejects.toThrow('Aborted');
		}
		expect(dem.fallback).toBe(false);
	});
});

/** A bumpy bordered grid, the same each run. */
function terrain(size: number, seed = 1): Float32Array {
	let s = seed;
	const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647) * 2 - 1;
	const n = size + 2;
	const g = new Float32Array(n * n);
	for (let r = 0; r < n; r++)
		for (let c = 0; c < n; c++)
			g[r * n + c] =
				1500 + 400 * Math.sin(r / 5) * Math.cos(c / 7) + 150 * Math.sin((r + c) / 2.3) + 25 * rnd();
	return g;
}

/** The overlay painting as it was before PR 4: Horn per pixel, straight to colour. */
function paintBefore(
	mode: TerrainMode,
	grid: Float32Array,
	size: number,
	z: number,
	y: number,
	match?: MatchParams
): Uint8ClampedArray | null {
	const stride = size + 2;
	const out = new Uint8ClampedArray(size * size * 4);
	const rules = match
		? match.rules.map((r) => ({
				mask: r.aspects.reduce((m, s) => m | (1 << SECTORS.indexOf(s)), 0),
				ranges: r.ranges
			}))
		: [];
	let any = false;
	for (let r = 0; r < size; r++) {
		const m = metresPerPixel(tileLat(y + (r + 0.5) / size, z), z, size);
		for (let c = 0; c < size; c++) {
			const { slope, aspect } = hornAt(grid, stride, r + 1, c + 1, m, m);
			let on: number | null = null;
			if (mode === 'slope') {
				const k = slopeClass(slope);
				if (k >= 0) on = k;
			} else if (mode === 'aspect') {
				if (slope >= FLAT_DEG) on = Math.round(aspect / 45) % 8;
			} else if (match && slope >= match.slopeMin) {
				if (matches(rules, aspect, grid[(r + 1) * stride + c + 1])) on = 0;
			}
			if (on != null) {
				out[(r * size + c) * 4 + 3] = 255;
				out[(r * size + c) * 4] = on;
				any = true;
			}
		}
	}
	return any ? out : null;
}

describe('slope and aspect kept, then coloured', () => {
	const size = 64;
	const match: MatchParams = {
		slopeMin: 30,
		rules: [
			{ aspects: ['N', 'NE', 'W'], ranges: [[1400, 1700]] },
			{ aspects: ['S'], ranges: [] }
		]
	};

	it('draws the same pixels as before, in every mode', () => {
		for (const seed of [1, 7, 42]) {
			const g = terrain(size, seed);
			const k = classify(g, size, 12, 1388);
			const elev = unborder(g, size);
			for (const mode of ['slope', 'aspect', 'match'] as const) {
				const now = paintClasses(mode, k, elev, size, match);
				const was = paintBefore(mode, g, size, 12, 1388, match);
				expect(!!now).toBe(!!was);
				if (!now || !was) continue;
				// Where something is drawn: the same pixels.
				for (let j = 3; j < now.length; j += 4) expect(now[j]).toBe(was[j]);
			}
			// And `paint` is the two together.
			expect(paint('slope', g, size, 12, 1388)).toEqual(paintClasses('slope', k, elev, size));
		}
	});

	it('keeps slope to a hundredth of a degree and aspect as its sector', () => {
		const g = terrain(size, 3);
		const k = classify(g, size, 12, 1388);
		const m = metresPerPixel(tileLat(1388 + 10.5 / size, 12), 12, size);
		const { slope, aspect } = hornAt(g, size + 2, 11, 21, m, m);
		expect(k.slope[10 * size + 20]).toBe(Math.floor(slope * 100));
		expect(k.sector[10 * size + 20]).toBe(Math.round(aspect / 45) % 8);
	});
});

describe('the concern class on its own', () => {
	const p: ConcernParams = {
		slope: [
			[25, 0.4],
			[30, 1],
			[46, 0.6]
		],
		matchListed: 1.4,
		matchOther: 0.8,
		matchNone: 1,
		windLoaded: 0.6,
		windScoured: -0.4,
		windEffect: 0.25,
		sun: 0.5,
		sunHours: 4,
		classes: [1.5, 2.5, 3.5]
	};
	const inputs: ConcernInputs[] = [
		{
			danger: { alpine: 3, treeline: 2, below: 1 },
			treeline: [1400, 1900],
			problems: [
				{ name: 'Wind slab', aspects: ['N', 'NE', 'E'], bands: ['alpine', 'treeline'] },
				{ name: 'Wet', aspects: [], bands: ['below'] }
			],
			wind: true,
			windLoading: true,
			sun: true
		},
		{
			danger: { alpine: 4, treeline: null, below: 2 },
			treeline: [1200, 1700],
			problems: [],
			wind: false,
			windLoading: false,
			sun: false
		}
	];

	it('is what concernAt says, everywhere', () => {
		let s = 9;
		const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
		for (const inp of inputs)
			for (let n = 0; n < 2000; n++) {
				const elev = 800 + rnd() * 2400;
				const slope = rnd() * 60;
				const aspect = rnd() * 360;
				const wind = rnd() < 0.2 ? null : rnd() * 2 - 1;
				const sunHours = rnd() < 0.2 ? null : rnd() * 9;
				const want = concernAt({ elev, slope, aspect, wind, sunHours }, inp, p).cls;
				const sector = Math.round(aspect / 45) % 8;
				expect(concernCls(elev, slope, sector, wind, sunHours, inp, p)).toBe(want);
			}
	});
});

describe('the problems query in one form', () => {
	it('is the same however the rules are listed', () => {
		const a: MatchParams = {
			slopeMin: 30,
			rules: [
				{
					aspects: ['W', 'N'],
					ranges: [
						[1500, 3000],
						[0, 1500]
					]
				},
				{ aspects: ['S'], ranges: [] },
				{ aspects: ['N', 'W'], ranges: [[0, 3000]] }
			]
		};
		const b: MatchParams = {
			slopeMin: 30,
			rules: [
				{ aspects: ['S'], ranges: [] },
				{ aspects: ['N', 'W'], ranges: [[0, 3000]] }
			]
		};
		expect(matchQuery(a, 'z1')).toBe(matchQuery(b, 'z1'));
		// And it still means the same terrain.
		expect(parseMatch(matchQuery(a))).toEqual({
			slopeMin: 30,
			rules: [
				{ aspects: ['N', 'W'], ranges: [[0, 3000]] },
				{ aspects: ['S'], ranges: [] }
			]
		});
	});

	it('keeps ranges apart when they don’t touch', () => {
		const q = matchQuery({
			slopeMin: 35,
			rules: [
				{
					aspects: ['E'],
					ranges: [
						[2000, 2500],
						[0, 900]
					]
				}
			]
		});
		expect(parseMatch(q)?.rules[0].ranges).toEqual([
			[0, 900],
			[2000, 2500]
		]);
	});
});

describe('job rectangles', () => {
	it('snap outward to whole steps, so a small move stays inside', () => {
		const r = { z: 12, x0: 1000, y0: 2013, width: 700, height: 500 };
		const s = snap(r, 32);
		expect(s).toEqual({ z: 12, x0: 992, y0: 1984, width: 736, height: 544 });
		expect(contains(s, r)).toBe(true);
		expect(contains(s, { ...r, x0: 1010 })).toBe(true);
		expect(contains(s, { ...r, x0: 1040 })).toBe(false);
		expect(contains(s, { ...r, z: 11 })).toBe(false);
	});
});

describe('the wind effect between rays', () => {
	function ridge(): Grid {
		const W = 80;
		const H = 60;
		const data = new Float32Array(W * H);
		for (let r = 0; r < H; r++)
			for (let c = 0; c < W; c++) data[r * W + c] = 1500 + 300 * Math.exp(-(((c - 40) / 8) ** 2));
		return { z: 11, x0: 0, y0: 0, width: W, height: H, data, m: 25 };
	}

	it('pauses six times a direction, and the result is the same', async () => {
		const g = ridge();
		const sectors = [0, 0, 0, 0, 0, 0, 0.5, 0.5];
		let pauses = 0;
		const withPauses = await windEffect(g, sectors, async () => (pauses++, true));
		const without = await windEffect(g, sectors);
		expect(pauses).toBe(12);
		expect(withPauses).toEqual(without);
	});

	it('stops within a ray when told to', async () => {
		let pauses = 0;
		const r = await windEffect(ridge(), [0, 0, 0, 0, 0, 0, 1, 0], async () => ++pauses < 2);
		expect(r).toBeNull();
		expect(pauses).toBe(2);
	});
});
