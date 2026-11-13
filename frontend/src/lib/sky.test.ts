// The sky's scene comes from the current hour only, so it never changes while you scrub.
import { describe, expect, it } from 'vitest';
import { hourIndex, pickScene, SCENE_LABEL, sceneIcon, type Scene } from './sky';
import type { HourlyOut, SunDay } from './types.gen';

/** Three hours from 2 PM, with the given values for every hour unless overridden. */
function hours(v: Partial<Record<keyof HourlyOut, (number | null)[]>> = {}): HourlyOut {
	const t = ['2026-11-04T14:00-07:00', '2026-11-04T15:00-07:00', '2026-11-04T16:00-07:00'];
	const fill = (x: number) => t.map(() => x);
	return {
		t,
		snow_cm: fill(0),
		rain_mm: fill(0),
		cloud: fill(0),
		wcode: fill(0),
		is_day: fill(1),
		...v
	} as unknown as HourlyOut;
}
const sun: SunDay[] = [
	{
		date: '2026-11-04',
		sunrise: '2026-11-04T07:00-07:00',
		sunset: '2026-11-04T17:00-07:00',
		daylight_s: 36000
	}
];

describe('pickScene', () => {
	it('reads cloud cover when nothing falls', () => {
		expect(pickScene(hours()).scene).toBe('clear');
		expect(pickScene(hours({ cloud: [50, 50, 50] })).scene).toBe('partly');
		expect(pickScene(hours({ cloud: [95, 95, 95] })).scene).toBe('overcast');
	});

	it('puts precipitation ahead of cloud', () => {
		expect(pickScene(hours({ snow_cm: [0.3, 0, 0], cloud: [100, 100, 100] })).scene).toBe('snow');
		expect(pickScene(hours({ snow_cm: [1, 1, 0.5] })).scene).toBe('heavy');
		expect(pickScene(hours({ snow_cm: [0.3, 0, 0], rain_mm: [0.5, 0, 0] })).scene).toBe('mixed');
		expect(pickScene(hours({ rain_mm: [1, 0, 0] })).scene).toBe('rain');
		expect(pickScene(hours({ wcode: [45, 45, 45] })).scene).toBe('fog');
	});

	it('turns a clear sky near sunset into alpenglow, and after dark into night', () => {
		const late = hours();
		late.t = ['2026-11-04T16:30-07:00', '2026-11-04T17:30-07:00', '2026-11-04T18:30-07:00'];
		expect(pickScene(late, sun).scene).toBe('glow');
		const dark = hours({ is_day: [0, 0, 0] });
		dark.t = ['2026-11-04T21:00-07:00', '2026-11-04T22:00-07:00', '2026-11-04T23:00-07:00'];
		expect(pickScene(dark, sun)).toMatchObject({ scene: 'night', night: true });
	});

	it('keeps a snowy night snowy, flagged as night', () => {
		const s = pickScene(hours({ snow_cm: [0.4, 0, 0], is_day: [0, 0, 0] }), sun);
		expect(s).toMatchObject({ scene: 'snow', night: true, label: 'Light snow' });
	});

	it('finds the hour holding now', () => {
		const h = hours();
		expect(hourIndex(h, '2026-11-04T15:20-07:00')).toBe(1);
		expect(hourIndex(h, null)).toBe(0);
	});
});

describe('sceneIcon', () => {
	const icon = (scene: Scene, night = false) =>
		sceneIcon({ scene, night, label: SCENE_LABEL[scene] });
	it('gives every scene an icon', () => {
		expect(
			Object.fromEntries((Object.keys(SCENE_LABEL) as Scene[]).map((s) => [s, icon(s)]))
		).toEqual({
			clear: 'clear-day',
			night: 'clear-night',
			glow: 'clear-day',
			partly: 'partly-day',
			overcast: 'cloud',
			snow: 'snow',
			heavy: 'snow',
			mixed: 'mix',
			rain: 'rain',
			fog: 'fog'
		});
	});
	it('draws a partly cloudy night with the moon', () => {
		expect(icon('partly', true)).toBe('partly-night');
	});
});
