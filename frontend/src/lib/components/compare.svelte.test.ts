// Compare's Add list and group menu: the list ticks nothing by itself, searches and stops
// at four; the groups menu opens, renames and deletes.
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CompareGroups from './CompareGroups.svelte';
import CompareAdd from './CompareAdd.svelte';
import { emptyComparison, type Group } from '../compare';

describe('CompareAdd', () => {
	afterEach(cleanup);
	const items = Array.from({ length: 9 }, (_, i) => ({
		id: `l${i}`,
		name: `Location ${i}`,
		region: i % 2 ? 'WA Cascades' : 'BC',
		kind: 'resort',
		stat: '1.0 in',
		ready: i !== 8
	}));

	it('ticks nothing by itself, searches past 8, and stops at 4', async () => {
		const ontoggle = vi.fn();
		const { rerender } = render(CompareAdd, { items, picked: [], ontoggle });
		expect(screen.queryAllByRole('button', { pressed: true })).toHaveLength(0);
		await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'cascades' } });
		expect(screen.getAllByRole('button')).toHaveLength(4);
		await rerender({ items, picked: items.slice(0, 4).map((i) => i.id), ontoggle });
		await fireEvent.input(screen.getByRole('searchbox'), { target: { value: '' } });
		expect((screen.getByRole('button', { name: /Location 5/ }) as HTMLButtonElement).disabled).toBe(
			true
		);
		expect((screen.getByRole('button', { name: /Location 3/ }) as HTMLButtonElement).disabled).toBe(
			false
		);
		expect(screen.getByText(/4 of 4 picked/)).toBeTruthy();
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
