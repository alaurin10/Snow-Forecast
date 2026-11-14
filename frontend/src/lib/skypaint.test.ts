// The backdrop's colours follow the sun's height for every weather.
import { describe, expect, it } from 'vitest';
import { luminance, mix, skyPaint } from './skypaint';
import { WEATHERS } from './sky';

const lum = (c: string) => luminance(c);

describe('skyPaint', () => {
	it('darkens every weather from day to night, in both modes', () => {
		for (const dark of [false, true])
			for (const weather of WEATHERS) {
				const day = skyPaint({ weather, alt: 1 }, dark);
				const night = skyPaint({ weather, alt: -1 }, dark);
				expect(lum(night.k1), `${weather} ${dark}`).toBeLessThan(lum(day.k1));
			}
	});

	it('makes a snowy dusk dark blue-grey, not pale', () => {
		const dusk = skyPaint({ weather: 'snow', alt: -0.4 }, true);
		expect(lum(dusk.k1)).toBeLessThan(0.05);
		const [r, , b] = [1, 3, 5].map((i) => parseInt(dusk.k1.slice(i, i + 2), 16));
		expect(b).toBeGreaterThan(r);
	});

	it('changes continuously with the sun, with no jumps', () => {
		for (const weather of WEATHERS) {
			let prev = skyPaint({ weather, alt: -1 }, false).k2;
			for (let a = -0.95; a <= 1.001; a += 0.05) {
				const next = skyPaint({ weather, alt: a }, false).k2;
				expect(Math.abs(lum(next) - lum(prev)), `${weather} at ${a}`).toBeLessThan(0.08);
				prev = next;
			}
		}
	});

	it('warms a clear horizon at sunset, and much less under cloud', () => {
		const warmth = (c: string) => parseInt(c.slice(1, 3), 16) - parseInt(c.slice(5, 7), 16);
		const clearDay = skyPaint({ weather: 'clear', alt: 1 }, false).k2;
		const clearSet = skyPaint({ weather: 'clear', alt: 0.05 }, false).k2;
		const greySet = skyPaint({ weather: 'overcast', alt: 0.05 }, false).k2;
		const greyDay = skyPaint({ weather: 'overcast', alt: 1 }, false).k2;
		expect(warmth(clearSet) - warmth(clearDay)).toBeGreaterThan(60);
		expect(warmth(greySet) - warmth(greyDay)).toBeLessThan(warmth(clearSet) - warmth(clearDay));
	});

	it('shows stars and the moon only on a clear-ish night', () => {
		expect(skyPaint({ weather: 'clear', alt: -1 }, true).starO).toBeCloseTo(1);
		expect(skyPaint({ weather: 'clear', alt: 1 }, true).starO).toBe(0);
		expect(skyPaint({ weather: 'overcast', alt: -1 }, true).starO).toBeLessThan(0.15);
		expect(skyPaint({ weather: 'storm', alt: -1 }, true).moonO).toBe(0);
	});

	it('tells the weathers apart in light mode by day', () => {
		const keys = WEATHERS.map((weather) => skyPaint({ weather, alt: 1 }, false).k1);
		expect(new Set(keys).size).toBe(WEATHERS.length);
	});
});

describe('mix', () => {
	it('blends two colours', () => {
		expect(mix('#000000', '#ffffff', 0.5)).toBe('#808080');
		expect(mix('#102030', '#102030', 0.3)).toBe('#102030');
	});
});
