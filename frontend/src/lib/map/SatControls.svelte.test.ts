// The Recent satellite controls say which scene is shown, step between scenes and switch bands.
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SatControls from './SatControls.svelte';
import { data } from './sat.fixture';

describe('SatControls', () => {
	afterEach(cleanup);
	const now = new Date(2026, 10, 10, 12).getTime();
	const props = {
		data,
		loadState: 'ready' as const,
		index: 0,
		bands: 'natural' as const,
		zoom: 12,
		now,
		onbands: () => {}
	};

	it('names the scene shown and steps between a location’s scenes', async () => {
		const spot = data.locations![1];
		render(SatControls, { ...props, spot });
		expect(screen.getByRole('status').textContent).toContain('9 Nov · yesterday');
		expect(screen.getByText('1/2')).toBeTruthy();
		const older = screen.getByRole('button', { name: 'Older view' });
		await fireEvent.click(older);
		expect(screen.getByText('2/2')).toBeTruthy();
		expect(screen.getByRole('status').textContent).toContain('77% clear');
		expect((older as HTMLButtonElement).disabled).toBe(true);
	});

	it('tells of the wide view round the area, and shows it when the centre has none', async () => {
		const snoq = data.locations!.find((l) => l.id === 'snoqualmie')!;
		const wide = { ...snoq.composite!, view: '0123456789abcdef' };
		render(SatControls, { ...props, data: { ...data, wide_km: 36 }, spot: { ...snoq, wide } });
		await fireEvent.click(screen.getByRole('button', { name: 'About this view' }));
		expect(
			screen.getByText(/Round it, out to 36 km: the newest clear view at 30 m, 21 Oct–4 Nov/)
		).toBeTruthy();
		expect(screen.getByText(/VIIRS daily, 10 Nov beyond that/)).toBeTruthy();
		cleanup();
		const sunshine = data.locations![2];
		render(SatControls, { ...props, spot: { ...sunshine, wide } });
		const status = screen.getByRole('status').textContent ?? '';
		expect(status.trim().startsWith('21 Oct–4 Nov')).toBe(true);
		expect(status).toContain('30 m round Sunshine; no clear 10 m view in 60 days');
	});

	it('says when a location has no clear view, or none is near', () => {
		render(SatControls, { ...props, spot: data.locations![2] });
		expect(
			screen.getByText(/No clear Sentinel-2 view of Sunshine in the last 60 days/)
		).toBeTruthy();
		cleanup();
		render(SatControls, { ...props, spot: null, zoom: 7 });
		expect(screen.getByText(/Daily mosaic from 10 Nov/)).toBeTruthy();
	});

	it('asks to zoom in for detail, and switches the bands', async () => {
		const onbands = vi.fn();
		render(SatControls, { ...props, spot: data.locations![0], zoom: 8, onbands });
		expect(screen.getByRole('status').textContent).toContain('Zoom in for 10 m detail');
		await fireEvent.click(screen.getByRole('button', { name: 'Snow vs cloud' }));
		expect(onbands).toHaveBeenCalledWith('snow');
	});

	it('opens on the stitched view, says when the spot was seen, and that the newest pass was cloudy', async () => {
		const spot = data.locations!.find((l) => l.id === 'snoqualmie')!;
		render(SatControls, { ...props, spot });
		const status = screen.getByRole('status').textContent ?? '';
		// The dates come first, so they show even when the line is cut short.
		expect(status.trim().startsWith('21 Oct–4 Nov')).toBe(true);
		expect(status).toContain('Snoqualmie Pass seen');
		expect(status).toContain('2 passes');
		expect(status).not.toContain('Sentinel');
		// The longer story is behind the (i).
		expect(screen.queryByText(/The newest pass, 10 Nov, was cloudy there\./)).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: 'About this view' }));
		expect(screen.getByText(/The newest pass, 10 Nov, was cloudy there\./)).toBeTruthy();
		expect(screen.getByText(/last seen clearly 21 Oct/)).toBeTruthy();
		expect(screen.getByText('1/2')).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'Older view' }));
		expect(screen.getByRole('status').textContent).toContain('15 Oct');
	});
});
