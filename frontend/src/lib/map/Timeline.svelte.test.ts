// The weather controls: every layer to choose from, a loop or a window picker, and its key.
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { prefs } from '../prefs.svelte';
import { toTimeline } from '../radar';
import Timeline from './Timeline.svelte';
import { weatherView } from './weather';

const H = 3600;
const T = 1_800_000_000;
const tl = toTimeline({
	generated: '',
	bounds: [
		[31, -134],
		[57, -102]
	],
	width: 10,
	height: 10,
	frames: [],
	layers: {
		snowlevel: {
			frames: [3, 6, 9].map((h) => ({
				t: T + h * H,
				file: `sl${h}.png`,
				kind: 'forecast' as const
			}))
		},
		snowfall: {
			frames: [24, 48].map((hours) => ({
				t: T,
				file: `o${hours}.png`,
				kind: 'observed' as const,
				hours
			}))
		}
	}
});

const base = {
	units: 'metric' as const,
	frame: 0,
	playing: false,
	pickId: 24,
	pick: undefined,
	label: null,
	current: undefined,
	waiting: false,
	ready: new Set<string>(),
	loadError: null
};

describe('Timeline (weather controls)', () => {
	afterEach(cleanup);

	it('leaves the choice of layer to the row of types above it', () => {
		render(Timeline, { ...base, weather: 'snowfall', view: weatherView(tl, 'snowfall', 'gust') });
		expect(screen.queryByRole('group', { name: 'Show' })).toBeNull();
		expect(screen.queryByRole('button', { name: 'Clouds' })).toBeNull();
	});

	it('picks observed snowfall by window, with its key in cm', () => {
		const view = weatherView(tl, 'snowfall', 'gust');
		render(Timeline, { ...base, weather: 'snowfall', view, pick: view.picks[0] });
		expect(screen.getByRole('button', { name: 'Last 24 hours' }).getAttribute('aria-pressed')).toBe(
			'true'
		);
		expect(screen.getByLabelText('Key, cm')).toBeTruthy();
	});

	it('says when the snow total is adjusted to terrain', () => {
		const withTotals = toTimeline({
			generated: '',
			bounds: tl.bounds,
			width: 10,
			height: 10,
			frames: [],
			totals: [
				{
					hours: 24,
					window: 24,
					start: T,
					end: T + 24 * H,
					file: 't24.png',
					tiles: '/api/snowtiles/0123456789abcdef/{z}/{x}/{y}.png'
				}
			]
		});
		const view = weatherView(withTotals, 'totals', 'gust');
		expect(view.picks[0].tiles).toContain('/api/snowtiles/');
		render(Timeline, { ...base, weather: 'totals', view, pick: view.picks[0] });
		expect(screen.queryByText(/adjusted to terrain/)).toBeNull();
		cleanup();
		render(Timeline, { ...base, weather: 'totals', view, pick: view.picks[0], adjusted: true });
		const note = screen.getByText(/adjusted to terrain/);
		expect(note.parentElement?.getAttribute('title')).toMatch(/snow above the model's snow level/);
	});

	it('picks the snow total on a slider that stops at each window', () => {
		const total = (window: number) => ({
			hours: window,
			window,
			start: T,
			end: T + window * H,
			file: `t${window}.png`
		});
		const view = weatherView(
			toTimeline({
				generated: '',
				bounds: tl.bounds,
				width: 10,
				height: 10,
				frames: [],
				totals: [12, 72, 240].map(total)
			}),
			'totals',
			'gust'
		);
		expect(view.picks.map((p) => p.tick)).toEqual(['12h', '3d', '10d']);
		render(Timeline, { ...base, weather: 'totals', view, pickId: 72, pick: view.picks[1] });
		// A slider, not a row of buttons.
		expect(screen.queryByRole('group', { name: 'Window' })).toBeNull();
		const slider = screen.getByRole('slider', { name: 'Snow total window' }) as HTMLInputElement;
		expect([slider.min, slider.max, slider.value]).toEqual(['0', '2', '1']);
		expect(slider.getAttribute('aria-valuetext')).toMatch(/^Next 3 days, /);
		expect(screen.getByText('Next 3 days')).toBeTruthy();
		expect(screen.getByText(/^to /)).toBeTruthy();
	});

	it('plays the snow level forecast, with the drape key when zoomed in', () => {
		const view = weatherView(tl, 'snowlevel', 'gust');
		const current = view.frames[0];
		const label = { when: 'Fri 5 AM', rel: 'forecast · in 3 h' };
		render(Timeline, { ...base, weather: 'snowlevel', view, current, label });
		expect(screen.getByRole('slider', { name: 'Time' })).toBeTruthy();
		expect(screen.getByLabelText('Key, m')).toBeTruthy();
		cleanup();
		render(Timeline, { ...base, weather: 'snowlevel', view, current, label, snowLine: 1200 });
		expect(screen.getByText(/Snow above 1,350 m/)).toBeTruthy();
	});

	it("gives the temperature's 32 °F height at the map's centre when zoomed in", () => {
		const view = weatherView(tl, 'temp', 'gust');
		render(Timeline, { ...base, weather: 'temp', view });
		expect(screen.queryByText(/near/)).toBeNull();
		cleanup();
		render(Timeline, { ...base, weather: 'temp', view, freezeLine: 2700, units: 'imperial' });
		expect(screen.getByText(/32°F near 8,850 ft/)).toBeTruthy();
		cleanup();
		render(Timeline, { ...base, weather: 'temp', view, freezeLine: 0 });
		expect(screen.getByText(/Below 0°C down to sea level/)).toBeTruthy();
	});

	it('switches the wind between gusts and ridge level', async () => {
		render(Timeline, { ...base, weather: 'wind', view: weatherView(tl, 'wind', 'gust') });
		expect(screen.getByText("This layer isn't drawn yet.")).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'Ridge' }));
		expect(prefs.mapWind).toBe('ridge');
		expect(screen.getByLabelText('Key, km/h')).toBeTruthy();
	});
});
