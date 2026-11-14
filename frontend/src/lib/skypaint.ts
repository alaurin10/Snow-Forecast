// The backdrop's colours for a sky: every weather has a day and a night palette (and a
// deepened day palette for dark mode), and the colours slide between them with the sun's
// height, with a warm glow near the horizon that shows through as much as the cloud lets
// it. So a snowy dusk is dark blue-grey, not pale, and a clear evening turns rose first.
import type { SkyState, Weather } from './sky';

type Trio = [string, string, string];

interface WeatherLook {
	/** Light mode, by day: top, middle, horizon. */
	day: Trio;
	/** Dark mode, by day: deepened, never black. */
	dayDark: Trio;
	/** After dark (dark mode; light mode lifts it toward its day colours). */
	night: Trio;
	/** How much the cloud hides: the sun's disc, the dawn glow and the stars. */
	cover: number;
	/** The soft cloud banks' opacity. */
	cloud: number;
	/** Rain-dark cloud, not white. */
	grey?: boolean;
}

const LOOK: Record<Weather, WeatherLook> = {
	clear: {
		day: ['#4f9fec', '#93c8f6', '#dff0fc'],
		dayDark: ['#173f77', '#27609f', '#4a86bf'],
		night: ['#0c1229', '#172344', '#2c3a66'],
		cover: 0,
		cloud: 0
	},
	partly: {
		day: ['#62a8ea', '#a6d0f4', '#e6f1fa'],
		dayDark: ['#1b4275', '#2d5f97', '#5584b3'],
		night: ['#10172e', '#1b2647', '#33406a'],
		cover: 0.35,
		cloud: 0.6
	},
	overcast: {
		day: ['#8a9db3', '#b5c3d3', '#dfe5ec'],
		dayDark: ['#2a3446', '#3a475c', '#536178'],
		night: ['#141a26', '#1f2735', '#323c4e'],
		cover: 0.9,
		cloud: 0.9
	},
	fog: {
		day: ['#c5cdd6', '#dde2e8', '#f1f3f5'],
		dayDark: ['#2c3440', '#3d4652', '#59626f'],
		night: ['#1a1f28', '#272d38', '#3d4450'],
		cover: 0.95,
		cloud: 1
	},
	drizzle: {
		day: ['#8fa3b5', '#b6c5d1', '#dde5eb'],
		dayDark: ['#233241', '#344757', '#4e6476'],
		night: ['#131a24', '#1e2733', '#313c4b'],
		cover: 0.9,
		cloud: 0.9,
		grey: true
	},
	rain: {
		day: ['#6f8799', '#9fb2c0', '#cfdae2'],
		dayDark: ['#1f2d3a', '#2f4252', '#4a6072'],
		night: ['#10161f', '#1a222d', '#2b3542'],
		cover: 0.95,
		cloud: 1,
		grey: true
	},
	storm: {
		day: ['#4f5d72', '#7d8a9c', '#b8bfc9'],
		dayDark: ['#161d2a', '#252f40', '#3b475b'],
		night: ['#0b0f17', '#151b27', '#242c3b'],
		cover: 1,
		cloud: 1,
		grey: true
	},
	mixed: {
		day: ['#8f9fb6', '#b8c3d3', '#dfe3eb'],
		dayDark: ['#242f44', '#36445c', '#50607a'],
		night: ['#141a28', '#202839', '#343e53'],
		cover: 0.9,
		cloud: 0.9,
		grey: true
	},
	snow: {
		day: ['#a9bcd6', '#cbd8e8', '#eef3f9'],
		dayDark: ['#26324a', '#394966', '#566a8a'],
		night: ['#161d2f', '#232d45', '#3a4766'],
		cover: 0.85,
		cloud: 0.8
	},
	heavy: {
		day: ['#97a7bf', '#c3cedd', '#e9eef5'],
		dayDark: ['#222c42', '#34425e', '#4d5f80'],
		night: ['#131a2a', '#1f2840', '#34405c'],
		cover: 1,
		cloud: 1
	},
	blowing: {
		day: ['#b3c2d6', '#d6dfea', '#f3f6fa'],
		dayDark: ['#2a3650', '#3e4e6c', '#5d7090'],
		night: ['#171f31', '#252f48', '#3d4a6a'],
		cover: 0.7,
		cloud: 0.7
	}
};

/** The glow near the horizon: violet high up, rose, then peach at the horizon. */
const GLOW: Trio = ['#8aa4e6', '#f1b9b5', '#ffe3c4'];
const GLOW_DARK: Trio = ['#232a52', '#6d4468', '#b9705c'];

export interface SkyPaint {
	k1: string;
	k2: string;
	k3: string;
	/** Cloud colour and the cloud banks' opacity. */
	cloud: string;
	cloudO: number;
	/** The sun's halo: colour and opacity. */
	glow: string;
	glowO: number;
	/** Stars and the moon. */
	starO: number;
	moonO: number;
	/** The two ridgelines at the foot. */
	ridge1: string;
	ridge2: string;
	/** One colour that stands for the sky, to tint the glass with. */
	key: string;
}

const hex = (c: string): [number, number, number] => [
	parseInt(c.slice(1, 3), 16),
	parseInt(c.slice(3, 5), 16),
	parseInt(c.slice(5, 7), 16)
];
const toHex = (rgb: number[]) =>
	'#' +
	rgb
		.map((v) =>
			Math.round(Math.min(255, Math.max(0, v)))
				.toString(16)
				.padStart(2, '0')
		)
		.join('');

/** `a` → `b` by `t` (0 to 1), in sRGB. */
export function mix(a: string, b: string, t: number): string {
	const x = hex(a);
	const y = hex(b);
	return toHex(x.map((v, i) => v + (y[i] - v) * t));
}

const mix3 = (a: Trio, b: Trio, t: number): Trio => [
	mix(a[0], b[0], t),
	mix(a[1], b[1], t),
	mix(a[2], b[2], t)
];

/** Relative luminance (WCAG), 0 to 1. */
export function luminance(c: string): number {
	const [r, g, b] = hex(c).map((v) => {
		const s = v / 255;
		return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

const smooth = (a: number, b: number, x: number) => {
	const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
	return t * t * (3 - 2 * t);
};
const rgba = (c: string, a: number) => {
	const [r, g, b] = hex(c);
	return `rgba(${r}, ${g}, ${b}, ${a.toFixed(2)})`;
};

/** The colours for a sky, in light or dark mode. */
export function skyPaint(sky: Pick<SkyState, 'weather' | 'alt'>, dark: boolean): SkyPaint {
	const look = LOOK[sky.weather];
	// 0 at full night, 1 in full day; the change runs from deep twilight to a little
	// after sunrise.
	const daylight = smooth(-0.7, 0.15, sky.alt);
	// Light mode keeps its night lighter, so dark text on the sky stays legible.
	const night = dark ? look.night : mix3(look.night, look.day, 0.5);
	const day = dark ? look.dayDark : look.day;
	let k = mix3(night, day, daylight);
	// The glow: strongest at the horizon, fading by about two hours up or an hour down,
	// and only as much as the cloud lets through.
	const glowAmt =
		Math.max(0, 1 - Math.abs(sky.alt - 0.05) / (sky.alt >= 0.05 ? 0.6 : 0.45)) *
		(1 - look.cover * 0.8);
	k = mix3(k, dark ? GLOW_DARK : GLOW, glowAmt * 0.85);

	const clearness = 1 - look.cover;
	const nightAmt = 1 - daylight;
	const sunHalo = glowAmt > 0.3 ? 'rgba(255, 196, 160, 0.9)' : 'rgba(255, 248, 224, 0.95)';
	const cloudBase = look.grey
		? mix(dark ? '#5a6474' : '#e4e8ee', '#8a93a0', 0.25)
		: dark
			? '#aabad8'
			: '#ffffff';
	const cloudNight = dark ? '#3a4458' : '#8890a8';
	const cloud = mix(cloudBase, cloudNight, nightAmt * 0.8);
	return {
		k1: k[0],
		k2: k[1],
		k3: k[2],
		cloud: rgba(cloud, dark ? 0.3 + 0.2 * look.cover : 0.85),
		cloudO: look.cloud,
		glow: sky.alt < 0 ? 'rgba(255, 196, 160, 0.9)' : dark ? 'rgba(255, 226, 170, 0.35)' : sunHalo,
		// The sun's halo shows by day and in the glow, as the cloud allows.
		glowO: Math.max(daylight, glowAmt) * (1 - look.cover * 0.95),
		starO: smooth(0.5, 0.95, nightAmt) * clearness,
		moonO: smooth(0.4, 0.9, nightAmt) * Math.max(0, 1 - look.cover * 1.1),
		ridge1: dark
			? rgba(mix('#34466c', '#141c30', nightAmt), 0.55)
			: rgba(mix('#ffffff', '#3a4466', nightAmt * 0.7), 0.45),
		ridge2: dark
			? rgba(mix('#1e2c4a', '#0b1020', nightAmt), 0.75)
			: rgba(mix('#ffffff', '#2c3452', nightAmt * 0.7), 0.78),
		key: k[1]
	};
}
