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
		expect(screen.getByRole('status').textContent).toContain('Sentinel-2C · 9 Nov · yesterday');
		expect(screen.getByText('1/2')).toBeTruthy();
		const older = screen.getByRole('button', { name: 'Older scene' });
		await fireEvent.click(older);
		expect(screen.getByText('2/2')).toBeTruthy();
		expect(screen.getByRole('status').textContent).toContain('77% clear');
		expect((older as HTMLButtonElement).disabled).toBe(true);
	});

	it('says when a location has no clear view, or none is near', () => {
		render(SatControls, { ...props, spot: data.locations![2] });
		expect(
			screen.getByText(/No clear Sentinel-2 view of Sunshine in the last 30 days/)
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
});
