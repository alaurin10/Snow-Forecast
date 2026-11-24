// The Compare share image draws what the page shows: the window, the drawn lines in their
// colours, and the selected location picked out.
import { describe, expect, it } from 'vitest';
import whistler from '../fixtures/whistler.json';
import crystal from '../fixtures/crystal.json';
import type { Snapshot } from '../types.gen';
import { buildTimeline, windowFor, type Comparison } from '../compare';
import { drawCompareCard, SUMMARY_WORDS, windowWords } from './compareCard';
import type { Ctx, Palette } from './canvas';

const locs = [
	{ id: 'whistler', name: 'Whistler', snap: whistler as unknown as Snapshot },
	{ id: 'crystal', name: 'Crystal Mountain', snap: crystal as unknown as Snapshot }
];
const P = new Proxy({} as Palette, { get: (_t, k) => (k === 'dark' ? false : '#808080') });
const COLORS = ['#4a8fe7', '#dd6b20', '#c2479f', '#5b3fb5'];

/** A stand-in 2D context: records the text drawn and each stroke's colour, width and alpha. */
function fakeCtx() {
	const texts: string[] = [];
	const strokes: { color: string; width: number; alpha: number; points: number }[] = [];
	let points = 0;
	const state: Record<string, unknown> = { globalAlpha: 1, lineWidth: 1, strokeStyle: '#000' };
	const ctx = new Proxy(state, {
		get(t, k: string) {
			if (k in t) return t[k];
			if (k === 'measureText') return (s: string) => ({ width: s.length * 10 });
			if (k === 'fillText') return (s: string) => texts.push(s);
			if (k === 'beginPath') return () => (points = 0);
			if (k === 'moveTo' || k === 'lineTo') return () => points++;
			if (k === 'stroke')
				return () =>
					strokes.push({
						color: String(t.strokeStyle),
						width: Number(t.lineWidth),
						alpha: Number(t.globalAlpha),
						points
					});
			return () => {};
		},
		set(t, k: string, v) {
			t[k] = v;
			return true;
		}
	}) as unknown as Ctx;
	return { ctx, texts, strokes };
}

describe('the Compare share image', () => {
	const timeline = buildTimeline(locs, 'summit', 5);
	const cmp: Comparison = {
		locs: ['whistler', 'crystal'],
		on: ['whistler', 'crystal'],
		band: 'summit',
		metric: 'snow',
		range: 5
	};
	const win = windowFor(timeline.slots, 5, null);
	const base = {
		title: 'Washington touring',
		timeline,
		cmp,
		win,
		units: 'imperial' as const,
		colors: COLORS
	};

	it('draws each line in its colour, across the window, with its summary on top', () => {
		const { ctx, texts, strokes } = fakeCtx();
		drawCompareCard(ctx, 'portrait', { ...base, selected: null }, P);
		const lines = strokes.filter((s) => COLORS.includes(s.color) && s.points > 5);
		expect(lines.map((s) => s.color)).toEqual(['#4a8fe7', '#dd6b20']);
		expect(lines.every((s) => s.alpha === 1)).toBe(true);
		expect(texts).toContain('Washington touring');
		expect(texts).toContain('Whistler');
		expect(texts).toContain(SUMMARY_WORDS.snow);
		expect(texts.some((t) => /^\d+\.\d in$/.test(t))).toBe(true);
	});

	it('picks out the selected location: on top, bolder, the others stepped back', () => {
		const { ctx, strokes } = fakeCtx();
		drawCompareCard(ctx, 'landscape', { ...base, selected: 'whistler' }, P);
		const lines = strokes.filter((s) => COLORS.includes(s.color) && s.points > 5);
		const last = lines[lines.length - 1];
		expect(last.color).toBe('#4a8fe7');
		expect(last.alpha).toBe(1);
		expect(last.width).toBeGreaterThan(lines[0].width);
		expect(lines[0].alpha).toBeLessThan(1);
	});

	it('says so when no line is drawn', () => {
		const { ctx, texts } = fakeCtx();
		drawCompareCard(ctx, 'portrait', { ...base, cmp: { ...cmp, on: [] }, selected: null }, P);
		expect(texts).toContain('No lines drawn in this comparison.');
	});

	it('names the days in view', () => {
		const steps = timeline.slots.slice(win.off, win.off + win.n);
		expect(windowWords(steps)).toMatch(/^\w{3} \w{3} \d+ – \w{3} \w{3} \d+$/);
		expect(windowWords(steps.slice(0, 1))).toMatch(/^\w{3} \w{3} \d+$/);
	});
});
