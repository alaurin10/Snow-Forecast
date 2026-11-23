import { describe, expect, it } from 'vitest';
import whistler from './fixtures/whistler.json';
import crystal from './fixtures/crystal.json';
import rainy from './fixtures/rainy.json';
import type { Snapshot } from './types.gen';
import {
	addGroup,
	addLocation,
	align,
	buildTimeline,
	clean,
	cleanName,
	dayCells,
	dayStart,
	emptyComparison,
	findGroup,
	fromQuery,
	fzSide,
	hoursAhead,
	MAX_GROUPS,
	moveGroup,
	moveLocation,
	pickBand,
	placeLabels,
	readGroups,
	removeGroup,
	removeLocation,
	renameGroup,
	restoreGroup,
	stepValue,
	maxWindowTotal,
	summarizeSteps,
	windowTotals,
	toggleLine,
	toQuery,
	updateGroup,
	windowDays,
	windowFor,
	type Comparison,
	type Group
} from './compare';
import { buildSteps } from './charts/forecast';
import { dateOf } from './time';

const W = whistler as unknown as Snapshot;
const C = crystal as unknown as Snapshot;
const R = rainy as unknown as Snapshot;

const cmp = (locs: string[], on?: (string | null)[]): Comparison => ({
	...emptyComparison(),
	locs,
	on: on ?? locs.slice(0, 4)
});

describe('editing a comparison', () => {
	it('adds locations as lines while a colour is free, then as rows only', () => {
		let c = emptyComparison();
		for (const id of ['a', 'b', 'c', 'd', 'e']) c = addLocation(c, id);
		expect(c.locs).toEqual(['a', 'b', 'c', 'd', 'e']);
		expect(c.on).toEqual(['a', 'b', 'c', 'd']);
	});

	it('holds at most 8 locations and never adds one twice', () => {
		let c = emptyComparison();
		for (const id of ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'a']) c = addLocation(c, id);
		expect(c.locs).toHaveLength(8);
		expect(c.locs).not.toContain('i');
	});

	it('keeps every other line its colour when one is turned off', () => {
		const c = cmp(['a', 'b', 'c']);
		const off = toggleLine(c, 'b').cmp;
		expect(off.on).toEqual(['a', null, 'c']);
		// A new line takes the free colour in the middle, not the next one along.
		expect(toggleLine(off, 'b').cmp.on).toEqual(['a', 'b', 'c']);
		const withD = addLocation(off, 'd');
		expect(withD.on).toEqual(['a', 'd', 'c']);
	});

	it('refuses a fifth line and changes nothing', () => {
		const c = cmp(['a', 'b', 'c', 'd', 'e']);
		const r = toggleLine(c, 'e');
		expect(r.full).toBe(true);
		expect(r.cmp).toBe(c);
	});

	it('removing a location frees its colour and drops trailing free slots', () => {
		const c = removeLocation(cmp(['a', 'b', 'c']), 'c');
		expect(c.locs).toEqual(['a', 'b']);
		expect(c.on).toEqual(['a', 'b']);
		expect(removeLocation(cmp(['a', 'b', 'c']), 'b').on).toEqual(['a', null, 'c']);
	});

	it('moves a location up or down, and not past either end', () => {
		const c = cmp(['a', 'b', 'c']);
		expect(moveLocation(c, 'b', -1).locs).toEqual(['b', 'a', 'c']);
		expect(moveLocation(c, 'c', 1)).toBe(c);
		expect(moveLocation(c, 'a', -1)).toBe(c);
	});
});

describe('the URL', () => {
	it('round-trips a comparison and its group name', () => {
		const c: Comparison = {
			locs: ['rainy', 'crystal', 'whistler'],
			on: ['rainy', null, 'whistler'],
			band: 'summit',
			metric: 'fl',
			range: 10
		};
		const q = toQuery(c, 'Washington touring');
		const back = fromQuery(new URLSearchParams(q));
		expect(back?.cmp).toEqual(c);
		expect(back?.name).toBe('Washington touring');
		expect(q).toContain('loc=rainy,crystal,whistler');
	});

	it('is null without locations, and an empty comparison with an empty list', () => {
		expect(fromQuery(new URLSearchParams('band=mid'))).toBeNull();
		expect(fromQuery(new URLSearchParams('loc='))?.cmp.locs).toEqual([]);
	});

	it('drops unknown ids, repeats, bad values and anything past the limits', () => {
		const known = new Set(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i']);
		const got = fromQuery(
			new URLSearchParams('loc=a,zz,a,b,c,d,e,f,g,h,i&on=a,a,zz,b,c&band=top&metric=x&range=7'),
			known
		)!;
		expect(got.cmp.locs).toEqual(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']);
		expect(got.cmp.on).toEqual(['a', null, null, 'b']);
		expect(got.cmp.band).toBe('mid');
		expect(got.cmp.metric).toBe('snow');
		expect(got.cmp.range).toBe(5);
	});

	it('draws the first four as lines when the link says nothing about lines', () => {
		const got = fromQuery(new URLSearchParams('loc=a,b,c,d,e'))!;
		expect(got.cmp.on).toEqual(['a', 'b', 'c', 'd']);
	});

	it('rejects ids that could break out of the URL', () => {
		expect(clean({ locs: ['ok', '../x', 'a b', '<b>'] }).locs).toEqual(['ok']);
	});
});

describe('groups', () => {
	const g = (name: string): Group => ({ ...cmp(['a']), name });

	it('cleans names and refuses empty or repeated ones (any case)', () => {
		expect(cleanName('  Washington   touring ')).toBe('Washington touring');
		expect(cleanName('   ')).toBeNull();
		expect(cleanName('x'.repeat(60))).toHaveLength(40);
		expect(addGroup([], ' ', cmp(['a'])).error).toBe('name');
		expect(addGroup([g('Touring')], 'touring', cmp(['a'])).error).toBe('exists');
	});

	it('stops at 20 groups', () => {
		const many = Array.from({ length: MAX_GROUPS }, (_, i) => g(`G${i}`));
		expect(addGroup(many, 'One more', cmp(['a'])).error).toBe('full');
	});

	it('keeps an open group’s changes under its own name', () => {
		const groups = updateGroup([g('Touring')], 'touring', { ...cmp(['a', 'b']), band: 'summit' });
		expect(groups[0]).toMatchObject({ name: 'Touring', locs: ['a', 'b'], band: 'summit' });
	});

	it('renames, refusing a name another group has', () => {
		const groups = [g('A'), g('B')];
		expect(renameGroup(groups, 'A', 'B').error).toBe('exists');
		expect(renameGroup(groups, 'A', 'a').groups.map((x) => x.name)).toEqual(['a', 'B']);
	});

	it('removes a group and puts it back where it was', () => {
		const groups = [g('A'), g('B'), g('C')];
		const r = removeGroup(groups, 'b');
		expect(r.groups.map((x) => x.name)).toEqual(['A', 'C']);
		expect(restoreGroup(r.groups, r.removed!).map((x) => x.name)).toEqual(['A', 'B', 'C']);
	});

	it('reorders', () => {
		expect(moveGroup([g('A'), g('B')], 'B', -1).map((x) => x.name)).toEqual(['B', 'A']);
	});

	it('reads back what was saved, and survives bad or old data', () => {
		const saved = JSON.stringify([
			{
				name: 'Touring',
				locs: ['rainy', 'crystal'],
				on: ['rainy'],
				band: 'summit',
				metric: 'snow',
				range: 10
			},
			{ name: 'touring', locs: ['x'] },
			{ name: '', locs: ['x'] },
			null,
			'junk',
			{ name: 'Old', locs: ['a', 'a', 'b'], band: 'peak' }
		]);
		const groups = readGroups(saved);
		expect(groups.map((x) => x.name)).toEqual(['Touring', 'Old']);
		expect(findGroup(groups, 'TOURING')?.range).toBe(10);
		expect(groups[1]).toMatchObject({ locs: ['a', 'b'], on: ['a', 'b'], band: 'mid' });
		expect(readGroups('{not json')).toEqual([]);
		expect(readGroups('{"a":1}')).toEqual([]);
		expect(readGroups(null)).toEqual([]);
	});
});

describe('one timeline for every location', () => {
	const locs = [
		{ id: 'crystal', name: 'Crystal', snap: C },
		{ id: 'whistler', name: 'Whistler', snap: W },
		{ id: 'rainy', name: 'Rainy', snap: R }
	];

	it('knows Whistler’s clock is an hour ahead of Crystal’s here', () => {
		const t = buildTimeline(locs, 'summit', 5);
		const off = Object.fromEntries(t.tracks.map((x) => [x.id, x.offset]));
		expect(off).toEqual({ crystal: '-08:00', whistler: '-07:00', rainy: '-08:00' });
		expect(hoursAhead(off.whistler, off.crystal)).toBe(1);
	});

	it('lines up 6-hour steps an hour apart, one step per slot, in time order', () => {
		const t = buildTimeline(locs, 'summit', 5);
		const wh = t.tracks.find((x) => x.id === 'whistler')!;
		const placed = wh.steps.filter((s) => s !== null);
		expect(placed.length).toBeGreaterThan(t.slots.length - 3);
		t.slots.forEach((slot, k) => {
			const s = wh.steps[k];
			if (!s) return;
			// Within half a step of the slot (an hour here).
			expect(Math.abs(Date.parse(s.t) - Date.parse(slot.t))).toBeLessThan(3 * 3600e3);
		});
		const times = placed.map((s) => Date.parse(s!.t));
		expect(new Set(times).size).toBe(times.length);
		expect([...times].sort((a, b) => a - b)).toEqual(times);
	});

	it('lines up hourly steps exactly by time', () => {
		const t = buildTimeline(locs, 'mid', 1);
		const wh = t.tracks.find((x) => x.id === 'whistler')!;
		t.slots.forEach((slot, k) => {
			if (wh.steps[k]) expect(Date.parse(wh.steps[k]!.t)).toBe(Date.parse(slot.t));
		});
	});

	it('lines up day and night halves by the location’s own date', () => {
		const t = buildTimeline(locs, 'mid', 10);
		const wh = t.tracks.find((x) => x.id === 'whistler')!;
		t.slots.forEach((slot, k) => {
			const s = wh.steps[k];
			if (!s) return;
			expect(dateOf(s.t)).toBe(dateOf(slot.t));
			expect(s.night).toBe(slot.night);
		});
	});

	it('takes the slots from the freshest forecast', () => {
		const older = { ...W, generated_at: '2026-11-04T09:00:00+00:00' };
		const t = buildTimeline(
			[
				{ id: 'whistler', name: 'Whistler', snap: older },
				{ id: 'crystal', name: 'Crystal', snap: C }
			],
			'mid',
			3
		);
		expect(t.ref?.id).toBe('crystal');
	});

	it('leaves gaps rather than shifting a step that has no partner', () => {
		const slots = buildSteps(C.bands[1].hourly, 3, true);
		// A location whose data starts a day late.
		const late = slots.slice(8);
		const got = align(slots, late);
		expect(got.slice(0, 8).every((s) => s === null)).toBe(true);
		expect(got[8]).toBe(late[0]);
	});

	it('falls back to mid when a band is missing', () => {
		const one = { ...C, bands: [C.bands[0], C.bands[1]] } as Snapshot;
		expect(pickBand(one, 'summit').band).toBe('mid');
	});

	it('has the reference location’s days, at most 10', () => {
		const t = buildTimeline(locs, 'mid', 5);
		expect(t.dates.length).toBeGreaterThan(5);
		expect(t.dates.length).toBeLessThanOrEqual(10);
		expect(t.dates[0]).toBe(dateOf(C.bands[1].hourly.t[0]));
	});

	it('draws snow as the running total, wind as gusts', () => {
		const st = buildSteps(W.bands[2].hourly, 5, true)[3];
		expect(stepValue(st, 'snow')).toBe(st.cum);
		expect(stepValue(st, 'wind')).toBe(st.gust);
		expect(stepValue(null, 'temp')).toBeNull();
	});
});

describe('the window and the days', () => {
	const t = buildTimeline([{ id: 'crystal', name: 'Crystal', snap: C }], 'mid', 3);

	it('starts now, moves by day, and stays inside the data', () => {
		const w0 = windowFor(t.slots, 3, null);
		expect(w0.off).toBe(0);
		expect(w0.n).toBe(24);
		const start = dayStart(t.slots, t.dates, 2);
		const w = windowFor(t.slots, 3, start);
		expect(dateOf(t.slots[w.off].t)).toBe(t.dates[2]);
		expect(windowDays(t.slots, w, t.dates).from).toBe(2);
		expect(windowFor(t.slots, 3, Date.parse('2030-01-01')).off).toBe(w0.maxOff);
	});

	it('adds up each day like the Calendar', () => {
		const band = C.bands[1];
		const cells = dayCells(band, t.dates);
		const d0 = t.dates[0];
		const snow = band.periods
			.filter((p) => p.date === d0)
			.reduce((a, p) => a + (p.snow_cm ?? 0), 0);
		expect(cells[0].snow).toBeCloseTo(snow, 6);
		expect(cells[1].flMin).toBe(
			Math.min(
				...band.hourly.t
					.map((x, i) => (dateOf(x) === t.dates[1] ? band.hourly.fl_m[i] : null))
					.filter((v): v is number => v !== null)
			)
		);
		expect(dayCells(band, ['1999-01-01'])[0].has).toBe(false);
	});

	it('sums the window from the steps the chart draws, so a row and its line agree', () => {
		const wt = buildTimeline([{ id: 'whistler', name: 'Whistler', snap: W }], 'summit', 5);
		const w = windowFor(wt.slots, 5, null);
		const inView = wt.tracks[0].steps.slice(w.off, w.off + w.n);
		const run = windowTotals(inView);
		const s = summarizeSteps(inView);
		expect(s.snow).toBeCloseTo(run[run.length - 1]!, 6);
		expect(s.gust).toBe(Math.max(...inView.map((x) => x!.gust!)));
		expect(windowTotals([null, inView[0]])[0]).toBeNull();
	});

	it('scales snow to the snowiest window anywhere in the forecast', () => {
		const wt = buildTimeline([{ id: 'whistler', name: 'Whistler', snap: W }], 'summit', 3);
		const st = wt.tracks[0].steps;
		const n = 24;
		const best = maxWindowTotal(st, n);
		for (let k = 0; k + n <= st.length; k += 5)
			expect(summarizeSteps(st.slice(k, k + n)).snow).toBeLessThanOrEqual(best + 1e-9);
		expect(maxWindowTotal(st.slice(0, 3), n)).toBeCloseTo(summarizeSteps(st.slice(0, 3)).snow, 9);
	});
});

describe('the freezing level against a location', () => {
	it('says snow below, wet near the snow line, too warm above it', () => {
		expect(fzSide(1500, 2000)).toEqual({ diff: -500, word: 'snow' });
		expect(fzSide(2200, 2000)?.word).toBe('wet');
		expect(fzSide(2400, 2000)?.word).toBe('warm');
		expect(fzSide(null, 2000)).toBeNull();
	});
});

describe('labels at the ends of the lines', () => {
	const at = (...ys: number[]) => ys.map((y, i) => ({ id: `l${i}`, at: y }));
	const ids = (xs: { id: string }[]) => xs.map((x) => x.id);

	it('puts well-spaced labels right at their lines', () => {
		const got = placeLabels(at(20, 80, 150), 17, 8, 200);
		expect(got.map((g) => g.px)).toEqual([20, 80, 150]);
	});

	it('spreads two close labels around their middle, a little each way', () => {
		const got = placeLabels(at(100, 110), 17, 8, 200);
		expect(got.map((g) => g.px)).toEqual([96.5, 113.5]);
	});

	it('gives no label to lines that end on top of each other, and keeps the rest', () => {
		// Two lines ending near 0 at the foot of the plot, one well clear of them.
		const got = placeLabels(at(171.5, 209, 210), 17, 7.5, 202.5);
		expect(ids(got)).toEqual(['l0']);
		expect(got[0].px).toBe(171.5);
		// Three at the same spot, and one alone.
		expect(ids(placeLabels(at(30, 100, 100, 101), 17, 8, 200))).toEqual(['l0']);
	});

	it('leaves out a bunch that would have to move too far from its lines', () => {
		// Lines 9 px apart, spread 17 px apart: four move the outer two 12 px (kept); five
		// move them 16 px (too far, so none).
		expect(placeLabels(at(100, 109, 118, 127), 17, 8, 300)).toHaveLength(4);
		expect(placeLabels(at(100, 109, 118, 127, 136), 17, 8, 300)).toEqual([]);
	});

	it('keeps the lines’ order and never overlaps', () => {
		const got = placeLabels(at(150, 40, 50, 120), 17, 8, 200);
		expect(ids(got)).toEqual(['l1', 'l2', 'l3', 'l0']);
		for (let i = 1; i < got.length; i++)
			expect(got[i].px - got[i - 1].px).toBeGreaterThanOrEqual(17);
	});

	it('stays inside the plot', () => {
		expect(placeLabels(at(195), 17, 8, 192).map((g) => g.px)).toEqual([192]);
		expect(placeLabels(at(196, 199), 17, 8, 192)).toEqual([]);
	});
});
