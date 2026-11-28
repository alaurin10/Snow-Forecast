// Milestone 4B on the map: the loops, totals and temperature to 16 days, marked "Less
// certain" 10 days out (the index's `less_certain_from`), with GFS past 10 days.
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { frameLabel, frameSource, toTimeline, totalSources, type PrecipIndex } from '../radar';
import Timeline from './Timeline.svelte';
import { markTick, tempSlider, totalMarks, totalWords, weatherView } from './weather';

const H = 3600;
const T = 1_800_000_000 - (1_800_000_000 % (6 * H)); // a synoptic hour: "now"

/** Radar to now, hourly to 48 h, 3-hourly to 84 h, 6-hourly to 384 h, as the server lists. */
function index(lessCertain: number | null = T + 240 * H, lastH = 384): PrecipIndex {
	const radar = [-2, -1, 0].map((h) => ({
		t: T + h * H,
		past: true,
		file: `r${h}.png`,
		south: '',
		kind: 'radar' as const,
		span_h: 0,
		data: `r${h}.bin`
	}));
	const hours = [
		...Array.from({ length: 48 }, (_, i) => [i + 1, 1]),
		...Array.from({ length: 12 }, (_, i) => [51 + 3 * i, 3]),
		...Array.from({ length: (lastH - 90) / 6 + 1 }, (_, i) => [90 + 6 * i, 6])
	];
	const forecast = hours.map(([h, span]) => ({
		t: T + h * H,
		past: false,
		file: `f${h}.png`,
		south: h <= 264 ? 'nbm' : '',
		kind: 'forecast' as const,
		span_h: span,
		src:
			h > 240 ? { north: 'gfs', south: h <= 264 ? 'nbm' : 'gfs' } : { north: 'gdps', south: 'nbm' },
		data: `f${h}.bin`
	}));
	return {
		version: 3,
		generated: '',
		bounds: [
			[31, -134],
			[57, -102]
		],
		width: 10,
		height: 10,
		frames: [...radar, ...forecast],
		...(lessCertain ? { less_certain_from: lessCertain } : {}),
		layers: {
			clouds: {
				frames: [6, 240, 246, 384].map((h) => ({
					t: T + h * H,
					file: `k${h}.webp`,
					kind: 'forecast' as const
				}))
			}
		}
	};
}

describe('the timeline to 16 days', () => {
	afterEach(cleanup);

	it('places the "Less certain" mark between the frames either side of 10 days', () => {
		const tl = toTimeline(index());
		expect(tl.lessCertainAt).toBe(T + 240 * H);
		const i = Math.floor(tl.lessCertain);
		// The 6-hour frame ending at 240 h stands for 237 h, the next for 243 h: half way.
		expect(tl.frames[i].t).toBe(T + 240 * H);
		expect(tl.lessCertain - i).toBeCloseTo(0.5);
		expect(tl.frames.at(-1)!.t).toBe(T + 384 * H);
		expect(weatherView(tl, 'radar', 'gust').lessCertain).toBe(tl.lessCertain);
		// Another loop finds it among its own frames.
		const clouds = weatherView(tl, 'clouds', 'gust');
		expect(clouds.lessCertain).toBe(1);
	});

	it('has no mark from an older server, or where the loop stops at 10 days', () => {
		expect(toTimeline(index(null)).lessCertain).toBe(-1);
		expect(toTimeline(index(T + 240 * H, 240)).lessCertain).toBe(-1);
	});

	it('names GFS past 10 days, and its days ahead', () => {
		const tl = toTimeline(index());
		const far = tl.frames.find((f) => f.t === T + 300 * H)!;
		expect(frameSource(far)).toBe("Forecast, 6-hour average: NOAA's GFS model.");
		const both = tl.frames.find((f) => f.t === T + 252 * H)!;
		expect(frameSource(both)).toMatch(/NOAA's GFS model in Canada, NOAA's National Blend/);
		expect(frameLabel(tl.frames.at(-1)!, T * 1000).rel).toBe('6-hour avg · in 16 days');
	});

	it('shows the mark under the slider: its tick, and its words where they fit', () => {
		const tl = toTimeline(index());
		const view = weatherView(tl, 'radar', 'gust');
		const props = {
			units: 'metric' as const,
			weather: 'radar' as const,
			view,
			frame: view.now,
			playing: false,
			pickId: 24,
			pick: undefined,
			current: view.frames[view.now],
			label: { when: 'Fri 4 AM', rel: 'radar · now' },
			waiting: false,
			ready: new Set<string>(),
			loadError: null
		};
		render(Timeline, props);
		const mark = screen.getByTitle('Less certain after 10 days');
		expect(mark.classList.contains('lc')).toBe(true);
		const at = (Number(mark.style.left.replace('%', '')) / 100) * (view.frames.length - 1);
		expect(at).toBeCloseTo(view.lessCertain, 5);
		// Without the room for them after it (this slider is ~300 px), the tick alone.
		expect(mark.textContent).toBe('');
		cleanup();
		// From an older server: no mark.
		const old = weatherView(toTimeline(index(null)), 'radar', 'gust');
		render(Timeline, { ...props, view: old, current: old.frames[old.now] });
		expect(screen.queryByTitle('Less certain after 10 days')).toBeNull();
	});
});

describe('the snow total and temperature to 16 days', () => {
	it('stops the snow total at 14 days and the end', () => {
		const steps = [6, 12, 24, 48, 72, 120, 168, 240, 260, 284, 308, 332, 356, 380];
		// The marks are places on the slider: between the steps it blends.
		expect(totalMarks(steps)).toEqual([12, 24, 48, 72, 120, 168, 240, 336, 380]);
		// A run ending before 14 days: the end follows 10 days.
		expect(totalMarks(steps.filter((h) => h <= 308))).toEqual([12, 24, 48, 72, 120, 168, 240, 308]);
		expect([markTick(336), markTick(380)]).toEqual(['14d', '16d']);
		expect(totalWords(380)).toBe('Next 16 days');
	});

	it('credits GFS for a total past 10 days', () => {
		const run = T - 6 * H;
		const total = {
			hours: 380,
			window: 384,
			start: T,
			end: T + 380 * H,
			file: 't380.png',
			runs: { gdps: run, nbm: run, gfs: run }
		};
		expect(totalSources(total)).toMatch(
			/^Canada: GDPS \(.+\)\. US: NOAA National Blend \(.+\)\. Then both: NOAA GFS \(.+\)\.$/
		);
	});

	it('marks the temperature to 16 days, stopping its player at 10', () => {
		const hours = [
			...Array.from({ length: 28 }, (_, i) => 1 + 3 * i),
			...Array.from({ length: 50 }, (_, i) => 88 + 6 * i)
		];
		const s = tempSlider(
			hours.map((h) => ({ t: T + h * H })),
			T
		)!;
		expect(s.ticks).toEqual(['Now', '12h', '1d', '2d', '3d', '5d', '7d', '10d', '16d']);
		expect(s.ticks[s.stop]).toBe('10d');
		// To 10 days only (an older server): no stop.
		const short = tempSlider(
			hours.filter((h) => h <= 240).map((h) => ({ t: T + h * H })),
			T
		)!;
		expect(short.stop).toBe(-1);
	});
});
