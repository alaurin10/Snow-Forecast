import { describe, expect, it } from 'vitest';
import whistler from './fixtures/whistler.json';
import crystal from './fixtures/crystal.json';
import type { BandOut, Snapshot, TrendRun } from './types.gen';
import {
	confidenceNote,
	confidenceOf,
	dayReads,
	trendRead,
	windowRead,
	type WindowRead
} from './confidence';

const snowy = whistler as unknown as Snapshot;
const dry = crystal as unknown as Snapshot;

describe('confidenceOf', () => {
	it('needs a range', () => {
		expect(confidenceOf(20, null, 30)).toBeNull();
		expect(confidenceOf(20, 10, undefined)).toBeNull();
	});
	it('calls a narrow range agreement, whatever the total', () => {
		expect(confidenceOf(0, 0, 2.2)).toBe('high');
		expect(confidenceOf(60, 58, 63)).toBe('high');
	});
	it('grades the range against the total', () => {
		expect(confidenceOf(50, 35, 65)).toBe('high'); // 60% of the total
		expect(confidenceOf(50, 20, 70)).toBe('medium'); // as wide as the total
		expect(confidenceOf(50, 10, 150)).toBe('low');
	});
	it('judges small totals against a floor, not against themselves', () => {
		// 3 cm forecast, 2–14 cm possible: wide for 3 cm, but only 12 cm in all.
		expect(confidenceOf(3, 2, 14)).toBe('medium');
		expect(confidenceOf(3, 0, 30)).toBe('low');
	});
});

describe('windowRead', () => {
	it('reads the next five days at mid-mountain from a snowy snapshot', () => {
		const r = windowRead(snowy.bands[1], 'next5');
		expect(r.snow_cm).toBe(snowy.bands[1].windows['next5'].snow_cm);
		expect(r.basis).toBe('ensemble');
		expect(r.lo).toBeLessThan(r.snow_cm!);
		expect(r.hi).toBeGreaterThan(r.snow_cm!);
		// Only the models that cover all ten periods, least snow first.
		expect(r.models.length).toBeGreaterThanOrEqual(3);
		expect(r.models.map((m) => m.cm)).toEqual([...r.models.map((m) => m.cm)].sort((a, b) => a - b));
		const gfs = snowy.bands[1].periods
			.slice(0, 10)
			.reduce((acc, p) => acc + (p.models['gfs_seamless'] ?? 0), 0);
		expect(r.models.find((m) => m.model === 'gfs_seamless')!.cm).toBeCloseTo(gfs, 5);
		expect(r.confidence).toBe('medium');
	});
	it('is less sure further out', () => {
		expect(windowRead(snowy.bands[1], 'd6_10').confidence).toBe('low');
	});
	it('is sure about a dry spell', () => {
		const r = windowRead(dry.bands[1], 'next5');
		expect(r.confidence).toBe('high');
		expect(confidenceNote(r)).toMatch(/Little or no snow/);
	});
	it('marks other elevations as estimated from mid', () => {
		expect(windowRead(snowy.bands[2], 'next5').estimated).toBe(true);
		expect(windowRead(snowy.bands[1], 'next5').estimated).toBe(false);
	});
	it('falls back to the models when there is no ensemble', () => {
		const band = structuredClone(snowy.bands[1]) as BandOut;
		band.windows['next5'].ens = null;
		const r = windowRead(band, 'next5');
		expect(r.basis).toBe('models');
		expect(r.lo).toBe(r.models[0].cm);
		expect(r.hi).toBe(r.models[r.models.length - 1].cm);
	});
	it('says so when nothing reaches', () => {
		const band = structuredClone(snowy.bands[1]) as BandOut;
		band.windows['d6_10'].ens = null;
		for (const p of band.periods) p.models = {};
		const r = windowRead(band, 'd6_10');
		expect(r.confidence).toBeNull();
		expect(confidenceNote(r)).toMatch(/Not enough models/);
	});
});

describe('confidenceNote', () => {
	const base: WindowRead = {
		key: 'next5',
		label: 'Next 5 days',
		snow_cm: 40,
		lo: 30,
		hi: 50,
		basis: 'ensemble',
		estimated: false,
		models: [],
		confidence: 'high'
	};
	it('has a sentence for each level', () => {
		expect(confidenceNote(base)).toMatch(/agree closely/);
		expect(confidenceNote({ ...base, confidence: 'medium' })).toMatch(/less on the amount/);
		expect(confidenceNote({ ...base, confidence: 'low' })).toMatch(/rough guide/);
	});
});

describe('dayReads', () => {
	it('gives every day its models, median and range', () => {
		const days = dayReads(snowy.daily);
		expect(days.length).toBe(snowy.daily.length);
		const d = days[2];
		const vals = Object.values(d.models).filter((v): v is number => v !== null);
		expect(vals.length).toBeGreaterThanOrEqual(3);
		expect(d.median).toBeGreaterThanOrEqual(Math.min(...vals));
		expect(d.median).toBeLessThanOrEqual(Math.max(...vals));
		expect(d.lo).toBeLessThanOrEqual(d.hi!);
	});
	it('has no median once fewer than three models remain', () => {
		const last = dayReads(snowy.daily).at(-1)!;
		const left = Object.values(last.models).filter((v) => v !== null).length;
		expect(left).toBeLessThan(3);
		expect(last.median).toBeNull();
	});
});

describe('trendRead', () => {
	const run = (id: number, daily: Record<string, number | null>): TrendRun => ({
		run_id: id,
		issued_at: `2026-11-0${id}T09:30:00+00:00`,
		next5_cm: null,
		daily
	});
	it('needs two runs', () => {
		expect(trendRead([])).toBeNull();
		expect(trendRead([run(1, { '2026-11-05': 4 })])).toBeNull();
	});
	it('compares the same days, so a storm leaving the window is not a change', () => {
		const t = trendRead([
			run(1, { '2026-11-04': 30, '2026-11-05': 5, '2026-11-06': 5 }),
			run(2, { '2026-11-05': 5, '2026-11-06': 12 })
		])!;
		expect(t.days).toBe(2);
		expect(t.change_cm).toBe(7);
		expect(t.direction).toBe('up');
		expect(t.runs_back).toBe(1);
	});
	it('calls a small move steady, and a drop down', () => {
		expect(trendRead([run(1, { a: 10 }), run(2, { a: 11 })])!.direction).toBe('steady');
		expect(trendRead([run(1, { a: 10 }), run(2, { a: 2 })])!.direction).toBe('down');
	});
	it('looks back at most five runs', () => {
		const runs = Array.from({ length: 8 }, (_, i) => run(i + 1, { a: i * 10 }));
		const t = trendRead(runs)!;
		expect(t.runs_back).toBe(4);
		expect(t.change_cm).toBe(40);
	});
});
