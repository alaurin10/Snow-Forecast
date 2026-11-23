// Compare's location rows and group menu: the name switches a line, cells fade outside the
// chart's days, Edit removes and reorders, and the groups menu opens, renames and deletes.
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CompareRows, { type RowView } from './CompareRows.svelte';
import CompareGroups from './CompareGroups.svelte';
import CompareAdd from './CompareAdd.svelte';
import crystal from '../fixtures/crystal.json';
import type { Snapshot } from '../types.gen';
import { buildTimeline, dayCells, emptyComparison, summarizeSteps, type Group } from '../compare';

const C = crystal as unknown as Snapshot;
const t = buildTimeline([{ id: 'crystal', name: 'Crystal Mountain', snap: C }], 'mid', 3);
const cells = dayCells(C.bands[1], t.dates);
const row = (id: string, name: string, slot: number): RowView => ({
	id,
	name,
	slot,
	state: 'ok',
	elev_m: 1800,
	bandLabel: 'Mid-mountain',
	cells,
	summary: summarizeSteps(t.tracks[0].steps.slice(0, 24)),
	stale: null
});

describe('CompareRows', () => {
	afterEach(cleanup);
	const base = {
		dates: t.dates,
		metric: 'snow' as const,
		units: 'imperial' as const,
		inView: { from: 1, to: 3 },
		whole: false,
		canPrev: true,
		canNext: true,
		sort: 'mine' as const,
		full: false,
		onsort: () => {},
		onremove: () => {},
		onmove: () => {},
		onadd: () => {},
		onday: () => {},
		onstep: () => {}
	};

	it('switches a line from its name, and says whether it is drawn', async () => {
		const ontoggle = vi.fn();
		render(CompareRows, {
			...base,
			rows: [row('crystal', 'Crystal Mountain', 0), row('rainy', 'Rainy Pass', -1)],
			ontoggle
		});
		const on = screen.getByRole('button', { name: /^Crystal Mountain: line drawn/ });
		expect(on.getAttribute('aria-pressed')).toBe('true');
		const off = screen.getByRole('button', { name: /^Rainy Pass: line hidden/ });
		expect(off.getAttribute('aria-pressed')).toBe('false');
		await fireEvent.click(off);
		expect(ontoggle).toHaveBeenCalledWith('rainy');
	});

	it('fades the days outside the chart and shows each one’s elevation', () => {
		const { container } = render(CompareRows, {
			...base,
			rows: [row('crystal', 'Crystal Mountain', 0)],
			ontoggle: () => {}
		});
		const boxes = [...container.querySelectorAll('.cellbox')];
		expect(boxes).toHaveLength(t.dates.length);
		expect(boxes.map((b) => b.classList.contains('in'))).toEqual(
			t.dates.map((_, k) => k >= 1 && k <= 3)
		);
		expect(container.textContent).toContain('5,900 ft');
	});

	it('Edit shows remove and reorder instead of the days', async () => {
		const onremove = vi.fn();
		const onmove = vi.fn();
		render(CompareRows, {
			...base,
			rows: [row('crystal', 'Crystal Mountain', 0), row('rainy', 'Rainy Pass', 1)],
			ontoggle: () => {},
			onremove,
			onmove
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
		expect(
			(screen.getByRole('button', { name: 'Move Crystal Mountain up' }) as HTMLButtonElement)
				.disabled
		).toBe(true);
		await fireEvent.click(screen.getByRole('button', { name: 'Move Crystal Mountain down' }));
		expect(onmove).toHaveBeenCalledWith('crystal', 1);
		await fireEvent.click(screen.getByRole('button', { name: 'Remove Rainy Pass' }));
		expect(onremove).toHaveBeenCalledWith('rainy');
		expect(
			(screen.getByRole('button', { name: /Add location/ }) as HTMLButtonElement).disabled
		).toBe(true);
	});

	it('puts the unit in the header, not in every cell', () => {
		const { container } = render(CompareRows, {
			...base,
			metric: 'wind',
			rows: [row('crystal', 'Crystal Mountain', 0)],
			ontoggle: () => {}
		});
		expect(container.querySelector('.head .sum')?.textContent).toBe('Top gust, mph');
		expect(container.querySelector('.cellbox')?.textContent).toMatch(/^\d+$/);
	});
});

describe('CompareAdd', () => {
	afterEach(cleanup);
	const items = Array.from({ length: 9 }, (_, i) => ({
		id: `l${i}`,
		name: `Location ${i}`,
		region: i % 2 ? 'WA Cascades' : 'BC',
		kind: 'resort',
		next5: '1.0 in',
		ready: i !== 8
	}));

	it('ticks nothing by itself, searches past 8, and stops at 8', async () => {
		const ontoggle = vi.fn();
		const { rerender } = render(CompareAdd, { items, picked: [], ontoggle });
		expect(screen.queryAllByRole('button', { pressed: true })).toHaveLength(0);
		await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'cascades' } });
		expect(screen.getAllByRole('button')).toHaveLength(4);
		await rerender({ items, picked: items.slice(0, 8).map((i) => i.id), ontoggle });
		await fireEvent.input(screen.getByRole('searchbox'), { target: { value: '' } });
		expect((screen.getByRole('button', { name: /Location 8/ }) as HTMLButtonElement).disabled).toBe(
			true
		);
		expect(screen.getByText(/8 of 8 picked/)).toBeTruthy();
	});
});

describe('CompareGroups', () => {
	afterEach(cleanup);
	const groups: Group[] = [
		{ ...emptyComparison(), name: 'Washington touring', locs: ['rainy', 'crystal'] },
		{ ...emptyComparison(), name: 'BC', locs: ['whistler'] }
	];
	const props = {
		groups,
		current: 'Washington touring',
		nameOf: (id: string) => id.toUpperCase(),
		onopen: () => {},
		onnew: () => {},
		onrename: () => null,
		onmove: () => {},
		ondelete: () => {}
	};

	it('lists groups with their locations and marks the open one', async () => {
		const onopen = vi.fn();
		render(CompareGroups, { ...props, onopen });
		const open = screen.getByRole('button', { name: /^Washington touring/ });
		expect(open.getAttribute('aria-current')).toBe('true');
		expect(open.textContent).toContain('2 locations: RAINY, CRYSTAL');
		await fireEvent.click(screen.getByRole('button', { name: /^BC/ }));
		expect(onopen).toHaveBeenCalledWith(groups[1]);
	});

	it('renames, showing the error it gets back', async () => {
		const onrename = vi.fn(() => 'You already have a group with that name.');
		render(CompareGroups, { ...props, onrename });
		await fireEvent.click(screen.getByRole('button', { name: 'Edit groups' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Rename BC' }));
		await fireEvent.input(screen.getByRole('textbox'), {
			target: { value: 'Washington touring' }
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		expect(onrename).toHaveBeenCalledWith('BC', 'Washington touring');
		expect(screen.getByRole('alert').textContent).toContain('already have');
	});

	it('deletes from Edit', async () => {
		const ondelete = vi.fn();
		render(CompareGroups, { ...props, ondelete });
		await fireEvent.click(screen.getByRole('button', { name: 'Edit groups' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Delete BC' }));
		expect(ondelete).toHaveBeenCalledWith('BC');
	});
});
