// The Sun & shade and Wind effect controls say what the layer shows and where it comes from.
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import TerrainControls from './TerrainControls.svelte';
import { sunDay, sunPosition } from './terrain/sun';
import type { WindSource } from './windsource';

const day = sunDay([2026, 12, 21], 50.06, -122.95);
const base = {
	units: 'metric' as const,
	tooFar: false,
	state: 'idle' as const,
	offline: false,
	sunMode: 'shade' as const,
	sunDate: '2026-12-21',
	sunTime: day.noon,
	day,
	position: sunPosition(day.noon, 50.06, -122.95),
	windWindow: 'next24' as const,
	wind: null,
	windLoaded: true
};
const wind: WindSource = {
	location: {
		id: 'whistler',
		name: 'Whistler',
		lat: 50.06,
		lon: -122.95,
		generated_at: '2026-12-21T12:00:00Z',
		roses: []
	},
	km: 12.4,
	rose: {
		window: 'next24',
		sectors: [0, 0, 0, 0, 0, 1, 0, 0],
		snow_cm: 18,
		mean_kmh: 42,
		wind_from: 'SW',
		loading: ['NE'],
		label: 'SW wind, loading NE aspects'
	},
	scale: 0.9
};

afterEach(cleanup);

describe('terrain controls', () => {
	it('shows the time of day, where the sun is, and that trees are not counted', () => {
		const { container } = render(TerrainControls, { ...base, overlay: 'sun' });
		const slider = screen.getByLabelText('Time of day') as HTMLInputElement;
		expect(Number(slider.min)).toBeGreaterThanOrEqual(day.sunrise!);
		expect(Number(slider.max)).toBeLessThanOrEqual(day.sunset!);
		expect(container.textContent).toMatch(/Sun 1[67]° up, S\b/);
		expect(container.textContent).toContain("Trees and cloud aren't counted");
		expect((screen.getByLabelText('Date') as HTMLInputElement).value).toBe('2026-12-21');
	});

	it('shows the key for sun hours', () => {
		const { container } = render(TerrainControls, { ...base, overlay: 'sun', sunMode: 'hours' });
		expect(container.textContent).toContain('Under 1 h');
		expect(container.textContent).toContain('8 h or more');
		expect(screen.queryByLabelText('Time of day')).toBeNull();
	});

	it('asks for a closer look when zoomed out, and says when terrain is missing offline', () => {
		const far = render(TerrainControls, { ...base, overlay: 'sun', tooFar: true });
		expect(far.container.textContent).toContain('Zoom in');
		far.unmount();
		const off = render(TerrainControls, {
			...base,
			overlay: 'sun',
			state: 'failed',
			offline: true
		});
		expect(off.container.textContent).toContain('No saved terrain');
	});

	it('names the wind, the snow and whose forecast it is', () => {
		const { container } = render(TerrainControls, { ...base, overlay: 'wind', wind });
		const text = container.textContent!.replace(/\s+/g, ' ');
		expect(text).toContain('SW wind 42 km/h, 18 cm of new snow');
		expect(text).toContain('Whistler summit forecast, 12 km away');
		expect(text).toContain("Local gusts and trees aren't modelled");
		expect(screen.getByRole('button', { name: 'Next 24 h' }).getAttribute('aria-pressed')).toBe(
			'true'
		);
	});

	it('explains an empty wind layer', () => {
		const none = render(TerrainControls, { ...base, overlay: 'wind' });
		expect(none.container.textContent).toContain('No saved location within 40 km');
		none.unmount();
		const calm = render(TerrainControls, {
			...base,
			overlay: 'wind',
			wind: {
				...wind,
				scale: 0,
				rose: { ...wind.rose!, wind_from: null, label: 'Little new snow to move' }
			}
		});
		expect(calm.container.textContent).toContain('Little new snow to move: nothing to show');
		calm.unmount();
		const old = render(TerrainControls, {
			...base,
			overlay: 'wind',
			wind: { ...wind, rose: null }
		});
		expect(old.container.textContent).toContain('after its next update');
	});
});
