// The radar drawn from numbers: the file format against the server's own encoder, the
// colours against the server's palette, which frames are fetched first, and the layer's
// choice of frames for the slider. (The drawing itself is checked in a real browser:
// e2e/radar.spec.ts.)
import { readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { describe, expect, it, vi } from 'vitest';
import { codeRate, halve, parse, rateCode, RATE_MAX, RATE_MIN } from './codec';
import { buildLut, CODE_FROM, CODE_SOLID, LUT_ROWS, LUT_WIDTH } from './palette';
import { FrameLoader, type WorkerLike } from './loader';
import { bracket } from './layer';
import type { LoadRequest, LoadResponse } from './frames.worker';
import type { Planes } from './codec';

const dir = new URL('./__fixtures__/', import.meta.url);
/** A 13 × 9 frame from backend/snowwatch/maps/dataframe.py, and what it decodes to there. */
const bin = readFileSync(new URL('frame.bin', dir));
const ref = JSON.parse(readFileSync(new URL('frame.json', dir), 'utf8')) as {
	rate: number[][];
	snow: number[][];
	mix: number[][];
	palette: { kind: 'snow' | 'mix' | 'rain'; mm: number; rgb: [number, number, number] }[];
};

describe('codec', () => {
	it("reads the server's frames exactly", () => {
		const p = parse(new Uint8Array(gunzipSync(bin)))!;
		expect(p).not.toBeNull();
		expect([p.width, p.height, p.typeWidth, p.typeHeight, p.ds]).toEqual([13, 9, 4, 3, 1]);
		expect([...p.rate]).toEqual(ref.rate.flat());
		expect([...p.type].filter((_, i) => i % 2 === 0)).toEqual(ref.snow.flat());
		expect([...p.type].filter((_, i) => i % 2 === 1)).toEqual(ref.mix.flat());
		expect(p.typeChannels).toBe(2);
	});
	it('reads a frame with the share the forecast filled in as a third type channel', () => {
		// Made by dataframe.encode with `filled` (the west whole, a band half, the east none).
		const filledBin = readFileSync(new URL('frame-filled.bin', dir));
		const want = JSON.parse(readFileSync(new URL('frame-filled.json', dir), 'utf8')) as {
			rate: number[][];
			snow: number[][];
			mix: number[][];
			filled: number[][];
		};
		const p = parse(new Uint8Array(gunzipSync(filledBin)))!;
		expect(p).not.toBeNull();
		expect(p.typeChannels).toBe(3);
		expect([...p.rate]).toEqual(want.rate.flat());
		const channel = (k: number) => [...p.type].filter((_, i) => i % 3 === k);
		expect(channel(0)).toEqual(want.snow.flat());
		expect(channel(1)).toEqual(want.mix.flat());
		expect(channel(2)).toEqual(want.filled.flat());
		expect(want.filled[0]).toEqual([0, 128, 255, 255]);
	});
	it('turns down anything else', () => {
		expect(parse(new Uint8Array(4))).toBeNull();
		const raw = new Uint8Array(gunzipSync(bin));
		expect(parse(raw.slice(0, raw.length - 1))).toBeNull();
		raw[0] = 0;
		expect(parse(raw)).toBeNull();
	});
	it('codes rates on the same scale as the server', () => {
		expect(codeRate(0)).toBe(0);
		expect(codeRate(1)).toBeCloseTo(RATE_MIN);
		expect(codeRate(127)).toBeCloseTo(RATE_MAX);
		expect(rateCode(0.01)).toBe(0);
		for (const mm of [0.1, 0.5, 2, 20]) expect(codeRate(rateCode(mm))).toBeCloseTo(mm, 6);
		// A 2 mm/h snow area in the fixture, within a code's step (6%).
		expect(codeRate(ref.rate[2][2])).toBeCloseTo(2, 0);
	});
	it('halves the rate plane by averaging codes', () => {
		const p: Planes = {
			rate: new Uint8Array([10, 20, 30, 40, 50, 60]),
			width: 3,
			height: 2,
			type: new Uint8Array(2),
			typeWidth: 1,
			typeHeight: 1,
			typeChannels: 2,
			ds: 1
		};
		const h = halve(p);
		expect([h.width, h.height, h.ds]).toEqual([2, 1, 2]);
		expect([...h.rate]).toEqual([(10 + 20 + 40 + 50 + 2) >> 2, (30 + 30 + 60 + 60 + 2) >> 2]);
	});
});

describe('palette', () => {
	it("matches the server's colours at each of its steps", () => {
		const lut = buildLut();
		expect(lut.length).toBe(LUT_WIDTH * LUT_ROWS.length * 4);
		let worst = 0;
		for (const e of ref.palette) {
			const row = LUT_ROWS.indexOf(e.kind);
			// The shader reads the table with linear filtering between codes.
			const c = rateCode(e.mm);
			const i0 = Math.floor(c);
			const f = c - i0;
			for (let k = 0; k < 3; k++) {
				const a = lut[(row * LUT_WIDTH + i0) * 4 + k];
				const b = lut[(row * LUT_WIDTH + Math.min(LUT_WIDTH - 1, i0 + 1)) * 4 + k];
				worst = Math.max(worst, Math.abs(a + (b - a) * f - e.rgb[k]));
			}
		}
		expect(worst).toBeLessThanOrEqual(3);
	});
	it('fades in from 0.1 mm/h and is solid from 0.25', () => {
		expect(codeRate(CODE_FROM)).toBeCloseTo(0.1, 6);
		expect(codeRate(CODE_SOLID)).toBeCloseTo(0.25, 6);
	});
});

/** A worker that answers when told to. */
function fakeWorker() {
	const sent: LoadRequest[] = [];
	const w: WorkerLike & { sent: LoadRequest[]; answer: (r: LoadResponse) => void } = {
		sent,
		onmessage: null,
		postMessage: (m) => sent.push(m),
		terminate: vi.fn(),
		answer: (r) => w.onmessage?.({ data: r } as MessageEvent<LoadResponse>)
	};
	return w;
}
const planes = (): Planes => ({
	rate: new Uint8Array(1),
	width: 1,
	height: 1,
	type: new Uint8Array(2),
	typeWidth: 1,
	typeHeight: 1,
	typeChannels: 2,
	ds: 1
});
const wants = (n: number) =>
	Array.from({ length: n }, (_, at) => ({ key: `k${at}`, url: `/u${at}`, half: false, at }));
const loads = (w: ReturnType<typeof fakeWorker>) =>
	w.sent.filter((m) => m.type === 'load') as Extract<LoadRequest, { type: 'load' }>[];

describe('FrameLoader', () => {
	it('fetches the frames nearest the slider first, a few at a time', () => {
		const w = fakeWorker();
		const have = new Set<string>();
		const got: string[] = [];
		const l = new FrameLoader(
			w,
			(k) => (got.push(k), have.add(k)),
			(k) => have.has(k)
		);
		l.want(wants(20));
		l.seek(10);
		// Six at once: the first asked for before the slider moved, then the nearest it.
		expect(loads(w)).toHaveLength(6);
		w.sent.length = 0;
		w.answer({ id: 1, ok: true, planes: planes() });
		// The next is whichever is nearest the slider now, ahead before behind.
		expect(loads(w).map((m) => m.url)).toEqual(['/u10']);
		l.seek(18);
		w.answer({ id: 2, ok: true, planes: planes() });
		expect(loads(w).map((m) => m.url)).toEqual(['/u10', '/u18']);
		expect(got).toEqual(['k0', 'k1']);
	});
	it('cancels fetches for frames no longer wanted, and tries failures again', () => {
		vi.useFakeTimers();
		const w = fakeWorker();
		let t = 0;
		const l = new FrameLoader(
			w,
			() => {},
			() => false,
			() => t
		);
		l.want(wants(2));
		expect(loads(w)).toHaveLength(2);
		l.want(wants(1));
		expect(w.sent.filter((m) => m.type === 'cancel')).toEqual([{ type: 'cancel', id: 2 }]);
		w.sent.length = 0;
		// A failure is tried again shortly, three times, then after a rest.
		for (let i = 0; i < 3; i++) {
			const id = Math.max(...loads(w).map((m) => m.id), 1);
			w.answer({ id, ok: false, error: 'x', aborted: false });
			expect(loads(w).filter((m) => m.id > id)).toHaveLength(0);
			t += 20_100;
			vi.advanceTimersByTime(20_100);
		}
		expect(loads(w).length).toBeGreaterThanOrEqual(3);
		l.dispose();
		expect(w.terminate).toHaveBeenCalled();
		vi.useRealTimers();
	});
});

describe('bracket', () => {
	it('gives the frames either side of the slider and how far between', () => {
		expect(bracket(2.25, 10)).toEqual({ i0: 2, i1: 3, f: 0.25 });
		expect(bracket(3, 10)).toEqual({ i0: 3, i1: 3, f: 0 });
		expect(bracket(3.9995, 10)).toEqual({ i0: 4, i1: 4, f: 0 }); // within a hair: that frame
		expect(bracket(-2, 10)).toEqual({ i0: 0, i1: 0, f: 0 });
		expect(bracket(12, 10)).toEqual({ i0: 9, i1: 9, f: 0 });
	});
});
