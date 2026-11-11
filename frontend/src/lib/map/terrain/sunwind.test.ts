// Sun position, cast shadows and the wind-shelter index, on synthetic terrain and
// against independent reference values.
import { describe, expect, it } from 'vitest';
import {
	around,
	bilinear,
	halve,
	into,
	mosaic,
	rectBounds,
	rectFor,
	rectMetres,
	worldX,
	worldY,
	type Grid
} from './grid';
import { TILE, type Elev } from './dem';
import { compass16, dateAt, daySteps, sunDay, sunPosition } from './sun';
import {
	cast,
	horizon,
	horizonAt,
	paintHours,
	paintShade,
	Shader,
	SOFT_M,
	sunClass,
	sunHours,
	sunTimes
} from './shade';
import {
	FAR_M,
	maxTan,
	NEAR_M,
	paintWind,
	rayOffsets,
	sx,
	transport,
	windEffect,
	windWeights,
	windWord
} from './wind';

const RAD = Math.PI / 180;

/** A grid of f(row, col) metres with `m` metres to the pixel, placed near Whistler. */
function grid(
	width: number,
	height: number,
	m: number,
	f: (r: number, c: number) => number,
	z = 12
): Grid {
	const data = new Float32Array(width * height);
	for (let r = 0; r < height; r++) for (let c = 0; c < width; c++) data[r * width + c] = f(r, c);
	return {
		z,
		x0: Math.round(worldX(-122.95, z)),
		y0: Math.round(worldY(50.1, z)),
		width,
		height,
		data,
		m
	};
}

const hills = (r: number, c: number) =>
	900 +
	500 * Math.exp(-((r - 40) ** 2 + (c - 50) ** 2) / 260) +
	350 * Math.exp(-((r - 75) ** 2 + (c - 85) ** 2) / 420) +
	250 * Math.exp(-((r - 90) ** 2 + (c - 30) ** 2) / 150);

/** Shade by marching a ray from the pixel toward the sun: slow, and plainly right. */
function rayShaded(g: Grid, r: number, c: number, azimuth: number, altitude: number): boolean {
	const sxp = Math.sin(azimuth * RAD);
	const syp = -Math.cos(azimuth * RAD);
	const t = Math.tan(altitude * RAD);
	const z0 = g.data[r * g.width + c];
	for (let d = 0.5; ; d += 0.5) {
		const px = c + 0.5 + d * sxp;
		const py = r + 0.5 + d * syp;
		if (px < 0.5 || py < 0.5 || px > g.width - 0.5 || py > g.height - 0.5) return false;
		if (bilinear(g.data, g.width, g.height, px, py) > z0 + d * g.m * t + 0.75) return true;
	}
}

describe('sun position', () => {
	// Reference values from PyEphem 4 (VSOP87), with standard refraction.
	const cases: [number, number, number, number, number][] = [
		[1797883200000, 47.6062, -122.3321, 178.17, 18.98], // Seattle, winter solstice noon
		[1782063000000, 47.6062, -122.3321, 112.73, 49.97], // Seattle, midsummer morning
		[1774018800000, 51.08, -115.77, 103.68, 10.9], // Sunshine Village, equinox morning
		[1800054900000, 39.6, -106.35, 234.65, 7.62], // Vail, January late afternoon
		[1794422700000, 37.63, -119.03, 164.22, 33.31], // Mammoth, November late morning
		[1797870600000, 50.1, -122.95, 131.25, 2.15] // Whistler, just after a December sunrise
	];
	it.each(cases)('matches the ephemeris at %i (%f, %f)', (ms, lat, lon, az, alt) => {
		const p = sunPosition(ms, lat, lon);
		expect(p.azimuth).toBeCloseTo(az, 0);
		expect(Math.abs(p.azimuth - az)).toBeLessThan(0.1);
		expect(Math.abs(p.altitude - alt)).toBeLessThan(0.1);
	});

	it('gives sunrise and sunset within a minute or two of the ephemeris', () => {
		const min = (a: number | null, iso: string) => Math.abs(a! - Date.parse(iso)) / 60000;
		const winter = sunDay([2026, 12, 21], 47.6062, -122.3321);
		expect(min(winter.sunrise, '2026-12-21T15:54:23Z')).toBeLessThan(2);
		expect(min(winter.sunset, '2026-12-22T00:20:44Z')).toBeLessThan(2);
		const summer = sunDay([2026, 6, 21], 47.6062, -122.3321);
		expect(min(summer.sunrise, '2026-06-21T12:11:14Z')).toBeLessThan(2);
		expect(min(summer.sunset, '2026-06-22T04:11:12Z')).toBeLessThan(2);
		const banff = sunDay([2027, 2, 1], 51.08, -115.77);
		expect(min(banff.sunrise, '2027-02-01T15:19:30Z')).toBeLessThan(2);
		expect(min(banff.sunset, '2027-02-02T00:34:24Z')).toBeLessThan(2);
	});

	it('is highest at solar noon, due south', () => {
		const day = sunDay([2026, 11, 11], 49, -120);
		const noon = sunPosition(day.noon, 49, -120);
		expect(noon.azimuth).toBeCloseTo(180, 0);
		expect(noon.altitude).toBeGreaterThan(sunPosition(day.noon - 600000, 49, -120).altitude);
		expect(noon.altitude).toBeGreaterThan(sunPosition(day.noon + 600000, 49, -120).altitude);
	});

	it('has no sunrise in the polar night and none to set in the midnight sun', () => {
		expect(sunDay([2026, 12, 21], 75, -120).sunrise).toBeNull();
		expect(sunDay([2026, 6, 21], 75, -120).sunset).toBeNull();
		expect(daySteps(sunDay([2026, 12, 21], 75, -120), 30).times).toEqual([]);
	});

	it('steps evenly through the day and adds up to its length', () => {
		const day = sunDay([2026, 12, 21], 47.6, -122.3);
		const { times, hours } = daySteps(day, 30);
		expect(times.length).toBe(17);
		expect(times.length * hours).toBeCloseTo((day.sunset! - day.sunrise!) / 3600000, 6);
		expect(times[0]).toBeGreaterThan(day.sunrise!);
		expect(times.at(-1)!).toBeLessThan(day.sunset!);
	});

	it('names the date at a longitude and a compass point', () => {
		// 03:00 UTC on the 12th is still the 11th in the Pacific zone.
		expect(dateAt(Date.UTC(2026, 10, 12, 3), -122)).toEqual([2026, 11, 11]);
		expect(dateAt(Date.UTC(2026, 10, 12, 9), -122)).toEqual([2026, 11, 12]);
		expect(compass16(200)).toBe('SSW');
		expect(compass16(-10)).toBe('N');
	});
});

describe('elevation grids', () => {
	it('picks the deepest zoom that fits and covers the bounds', () => {
		const b = around(50.1, -122.95, 4000);
		const fine = rectFor(b, 1024, 12);
		expect(fine.z).toBe(12);
		expect(rectMetres(fine)).toBeGreaterThan(11);
		expect(rectMetres(fine)).toBeLessThan(13.5);
		const [w, s, e, n] = rectBounds(fine);
		expect(w).toBeLessThanOrEqual(b[0]);
		expect(s).toBeLessThanOrEqual(b[1]);
		expect(e).toBeGreaterThanOrEqual(b[2]);
		expect(n).toBeGreaterThanOrEqual(b[3]);
		const small = rectFor(b, 256, 12);
		expect(small.z).toBe(10);
		expect(Math.max(small.width, small.height)).toBeLessThanOrEqual(257);
	});

	it('stitches tiles, each pixel from the right one', async () => {
		const asked: string[] = [];
		const dem = {
			elev: async (z: number, x: number, y: number): Promise<Elev> => {
				asked.push(`${z}/${x}/${y}`);
				const data = new Float32Array(TILE * TILE);
				for (let r = 0; r < TILE; r++)
					for (let c = 0; c < TILE; c++) data[r * TILE + c] = x * 1e6 + y * 1e3 + r + c / 1000;
				return { data, size: TILE, srcZ: z };
			}
		};
		const rect = { z: 5, x0: 3 * TILE - 2, y0: 7 * TILE - 3, width: 5, height: 6 };
		const g = (await mosaic(dem, rect))!;
		expect(asked.sort()).toEqual(['5/2/6', '5/2/7', '5/3/6', '5/3/7']);
		// Top-left comes from tile 2/6's last rows and columns; bottom-right from 3/7's first.
		expect(g.data[0]).toBeCloseTo(2e6 + 6e3 + (TILE - 3) + (TILE - 2) / 1000, 0);
		expect(g.data[5 * 5 + 4]).toBeCloseTo(3e6 + 7e3 + 2 + 2 / 1000, 0);
		expect(await mosaic(dem, rect, () => false)).toBeNull();
	});

	it('halves a grid and maps pixels between zooms', () => {
		const g = grid(8, 6, 10, (r, c) => r * 10 + c);
		const h = halve(g);
		expect([h.width, h.height, h.m, h.z]).toEqual([4, 3, 20, 11]);
		expect(h.data[0]).toBeCloseTo((0 + 1 + 10 + 11) / 4);
		const [px, py] = into(g, h, 4, 2);
		expect(px).toBeCloseTo(2);
		expect(py).toBeCloseTo(1);
	});
});

describe('cast shadows', () => {
	// A wall 100 m high running north–south at column 30, on flat ground, 10 m pixels.
	const wall = grid(60, 20, 10, (_, c) => (c === 30 ? 1100 : 1000));
	const shaded = (ceil: Float32Array, g: Grid, r: number, c: number) =>
		ceil[r * g.width + c] - g.data[r * g.width + c] >= SOFT_M;

	it('throws a shadow behind a ridge as long as the sun is low', () => {
		const buf = new Float32Array(wall.data.length);
		// Sun in the east, 30° up: 100 m / tan 30° = 173 m of shadow to the west.
		cast(wall, 90, 30, buf);
		for (const c of [29, 22, 14]) expect(shaded(buf, wall, 10, c)).toBe(true);
		for (const c of [11, 5, 31, 45]) expect(shaded(buf, wall, 10, c)).toBe(false);
		// Lower sun, longer shadow: 100 m / tan 15° = 373 m, off the grid's edge.
		cast(wall, 90, 15, buf);
		expect(shaded(buf, wall, 10, 0)).toBe(true);
		// From the west it falls the other way.
		cast(wall, 270, 30, buf);
		expect(shaded(buf, wall, 10, 40)).toBe(true);
		expect(shaded(buf, wall, 10, 20)).toBe(false);
	});

	it('works for a sun to the north or south of the grid', () => {
		const ridge = grid(20, 60, 10, (r) => (r === 30 ? 1100 : 1000));
		const buf = new Float32Array(ridge.data.length);
		cast(ridge, 180, 30, buf);
		expect(shaded(buf, ridge, 20, 10)).toBe(true); // north of the ridge, sun in the south
		expect(shaded(buf, ridge, 40, 10)).toBe(false);
		cast(ridge, 0, 30, buf);
		expect(shaded(buf, ridge, 40, 10)).toBe(true);
	});

	it('shades a slope that faces away from the sun more steeply than the sun is high', () => {
		// Falling 30° toward the west; the sun 20° up in the east never reaches it.
		const away = grid(40, 10, 10, (_, c) => 1000 + c * 10 * Math.tan(30 * RAD));
		const buf = new Float32Array(away.data.length);
		cast(away, 90, 20, buf);
		expect(shaded(buf, away, 5, 10)).toBe(true);
		cast(away, 90, 40, buf);
		expect(shaded(buf, away, 5, 10)).toBe(false);
		cast(away, 270, 20, buf);
		expect(shaded(buf, away, 5, 10)).toBe(false);
	});

	it('is all shade once the sun is down', () => {
		const buf = new Float32Array(wall.data.length);
		cast(wall, 250, -3, buf);
		expect(shaded(buf, wall, 3, 3)).toBe(true);
		expect(shaded(buf, wall, 10, 50)).toBe(true);
	});

	it.each([
		[135, 25],
		[200, 12],
		[250, 35],
		[75, 18],
		[315, 8],
		[20, 22]
	])('agrees with ray marching for the sun at %i°, %i° up', (az, alt) => {
		const g = grid(120, 120, 12, hills);
		const ceil = cast(g, az, alt, new Float32Array(g.data.length));
		let differ = 0;
		let total = 0;
		let dark = 0;
		for (let r = 4; r < 116; r += 2) {
			for (let c = 4; c < 116; c += 2) {
				const fast = ceil[r * 120 + c] - g.data[r * 120 + c] >= SOFT_M / 2;
				const slow = rayShaded(g, r, c, az, alt);
				total++;
				if (slow) dark++;
				if (fast !== slow) differ++;
			}
		}
		// There is real shadow to get right, and the sweep gets nearly all of it.
		expect(dark / total).toBeGreaterThan(0.08);
		expect(differ / total).toBeLessThan(0.03);
	});

	it('brings in shadow from mountains beyond the view', () => {
		// The view is flat. A 1,200 m mountain stands 6 km east of it, on the coarse grid only.
		const fine = grid(64, 64, 12.5, () => 1000);
		const coarse: Grid = {
			z: 10,
			x0: fine.x0 / 4 - 200,
			y0: fine.y0 / 4 - 200,
			width: 420,
			height: 420,
			m: 50,
			data: new Float32Array(420 * 420).fill(1000)
		};
		// East of the view's middle by 6 km = 120 coarse pixels.
		const mr = 200 + 8;
		const mc = 200 + 8 + 120;
		for (let r = 0; r < 420; r++)
			for (let c = 0; c < 420; c++)
				coarse.data[r * 420 + c] += 1200 * Math.exp(-((r - mr) ** 2 + (c - mc) ** 2) / 300);
		const alone = new Shader(fine).run(90, 8);
		expect(alone[32 * 64 + 32] - 1000).toBe(0);
		const both = new Shader(fine, coarse);
		// 8° up: the summit's shadow reaches 1200 / tan 8° = 8.5 km, past the view.
		expect(both.run(90, 8)[32 * 64 + 32] - 1000).toBeGreaterThan(100);
		// 20° up: it stops 3.3 km out, short of the view.
		expect(both.run(90, 20)[32 * 64 + 32] - 1000).toBe(0);
		// Sun in the west: the mountain is behind the view.
		expect(both.run(270, 8)[32 * 64 + 32] - 1000).toBe(0);
	});

	it('counts more sun on a south face than a north face in winter', async () => {
		// An east–west ridge: rows 0–39 face north, rows 41–79 face south, about 27° each.
		const g = grid(40, 80, 12, (r) => 1500 - Math.abs(r - 40) * 6);
		const hours = (await sunHours(new Shader(g), [2026, 12, 21], 50.1, -122.95))!;
		const north = hours[15 * 40 + 20];
		const south = hours[65 * 40 + 20];
		expect(north).toBe(0);
		expect(south).toBeGreaterThan(6);
		expect(south).toBeLessThanOrEqual(8.2);
		// Midsummer: both get most of a long day.
		const june = (await sunHours(new Shader(g), [2026, 6, 21], 50.1, -122.95))!;
		expect(june[15 * 40 + 20]).toBeGreaterThan(10);
		// Asked to stop: no answer.
		expect(
			await sunHours(new Shader(g), [2026, 12, 21], 50.1, -122.95, async () => false)
		).toBeNull();
	});

	it('paints shade dark with a soft edge, and sun hours by class', () => {
		const g = grid(3, 1, 10, () => 100);
		const px = paintShade(g, Float32Array.from([100, 100 + SOFT_M / 2, 400]));
		expect(px[3]).toBe(0);
		expect(px[7]).toBeGreaterThan(100);
		expect(px[7]).toBeLessThan(150);
		expect(px[11]).toBe(255);
		expect([0, 0.9, 1, 3.9, 7, 12].map(sunClass)).toEqual([0, 0, 1, 2, 4, 5]);
		const hp = paintHours(Float32Array.from([0, 9]));
		expect([hp[0], hp[1], hp[2], hp[3]]).toEqual([0x1d, 0x1b, 0x4b, 255]);
		expect(hp[4]).toBe(0xf9);
	});
});

describe('a spot and its horizon', () => {
	const lat = 50.1;
	const lon = -122.95;
	/** A grid centred on the spot. */
	function centred(size: number, m: number, f: (r: number, c: number) => number): Grid {
		const g = grid(size, size, m, f);
		return { ...g, x0: worldX(lon, g.z) - size / 2, y0: worldY(lat, g.z) - size / 2 };
	}

	it('is level on flat ground, so the sun shows from sunrise to sunset', () => {
		const h = horizon([centred(200, 12, () => 800)], lat, lon);
		expect(Math.max(...h)).toBe(0);
		const day = sunDay([2026, 11, 11], lat, lon);
		const s = sunTimes(h, [2026, 11, 11], lat, lon);
		expect(s.first! - day.sunrise!).toBeLessThan(6 * 60000);
		expect(day.sunset! - s.last!).toBeLessThan(6 * 60000);
		expect(s.hours).toBeCloseTo((day.sunset! - day.sunrise!) / 3600000, 0);
	});

	it('sees a wall to the south-east and loses the morning to it', () => {
		// 400 m high, 1 km away, filling the south-east quarter of the sky.
		const g = centred(240, 12, (r, c) => (r - 120 > 60 && c - 120 > 60 ? 1200 : 800));
		const h = horizon([g], lat, lon);
		expect(horizonAt(h, 135)).toBeGreaterThan(15);
		expect(horizonAt(h, 135)).toBeLessThan(22);
		expect(horizonAt(h, 315)).toBe(0);
		const open = sunTimes(new Float32Array(180), [2026, 11, 11], lat, lon);
		const s = sunTimes(h, [2026, 11, 11], lat, lon);
		expect(s.first! - open.first!).toBeGreaterThan(90 * 60000);
		expect(s.last).toBe(open.last);
		expect(s.hours).toBeLessThan(open.hours - 1.5);
	});

	it('carries on into a coarser grid where the fine one ends', () => {
		const fine = centred(100, 12, () => 800);
		const big = grid(300, 300, 48, () => 800, 10);
		const coarse: Grid = {
			...big,
			x0: worldX(lon, 10) - 150,
			y0: worldY(lat, 10) - 150
		};
		// A 1,000 m ridge 5 km to the south, beyond the fine grid (600 m each way).
		for (let r = 250; r < 262; r++) for (let c = 0; c < 300; c++) coarse.data[r * 300 + c] = 1800;
		const h = horizon([fine, coarse], lat, lon);
		expect(horizonAt(h, 180)).toBeGreaterThan(10);
		expect(horizonAt(h, 180)).toBeLessThan(13);
		expect(horizonAt(h, 0)).toBe(0);
		expect(horizon([fine], lat, lon)[90]).toBe(0);
	});

	it('reports no direct sun where the horizon is always higher', () => {
		const s = sunTimes(new Float32Array(180).fill(40), [2026, 12, 21], lat, lon);
		expect(s).toMatchObject({ first: null, last: null, hours: 0 });
		expect(s.sunrise).not.toBeNull();
	});
});

describe('wind effect', () => {
	// A ridge running north–south, 30° on both sides, 25 m pixels.
	const ridge = grid(160, 60, 25, (_, c) => 2000 - Math.abs(c - 80) * 25 * Math.tan(30 * RAD));

	it('steps rays in whole pixels, straight and on the diagonal', () => {
		const n = rayOffsets(0, 0, 3);
		expect(Array.from(n.dr)).toEqual([-1, -2, -3]);
		expect(Array.from(n.dc).map(Math.abs)).toEqual([0, 0, 0]);
		const se = rayOffsets(135, 0, 3);
		expect(Array.from(se.dr)).toEqual([1, 2]);
		expect(Array.from(se.dc)).toEqual([1, 2]);
		expect(se.dist[1]).toBeCloseTo(2 * Math.SQRT2);
		const far = rayOffsets(270, 4, 6);
		expect(Array.from(far.dc)).toEqual([-5, -6]);
	});

	it('finds the steepest way up, and nothing where the ray leaves the grid', () => {
		const g = grid(6, 1, 10, (_, c) => [0, 0, 0, 5, 30, 0][c]);
		const out = maxTan(g, rayOffsets(90, 0, 2), new Float32Array(6));
		expect(out[2]).toBeCloseTo(30 / 20); // 30 m up, two pixels east
		expect(out[3]).toBeCloseTo(25 / 10);
		expect(out[4]).toBeCloseTo(-3);
		expect(out[5]).toBe(-Infinity);
	});

	it('is negative on the windward side and positive in the lee', () => {
		const s = sx(ridge, 270, 0, NEAR_M);
		const at = (c: number) => s[30 * 160 + c];
		// West wind: the west slope looks down its own fall line, the east slope up to the crest.
		expect(at(40)).toBeLessThan(-25);
		expect(at(120)).toBeGreaterThan(25);
		expect(at(80)).toBeLessThan(-25); // the crest itself is exposed
		// Wind along the ridge shelters neither side much.
		expect(Math.abs(sx(ridge, 0, 0, NEAR_M)[30 * 160 + 40])).toBeLessThan(10);
	});

	it('loads the lee and strips the windward slope, and flips with the wind', async () => {
		const west = [0, 0, 0, 0, 0, 0, 1, 0];
		const e = (await windEffect(ridge, west))!;
		expect(e[30 * 160 + 120]).toBeGreaterThan(0.8);
		expect(e[30 * 160 + 40]).toBeLessThan(-0.8);
		const east = [0, 0, 1, 0, 0, 0, 0, 0];
		const f = (await windEffect(ridge, east))!;
		expect(f[30 * 160 + 120]).toBeLessThan(-0.8);
		expect(f[30 * 160 + 40]).toBeGreaterThan(0.8);
		// Wind from both sides in equal parts cancels on the slopes.
		const both = (await windEffect(ridge, [0, 0, 0.5, 0, 0, 0, 0.5, 0]))!;
		expect(Math.abs(both[30 * 160 + 120])).toBeLessThan(0.1);
		expect(await windEffect(ridge, west, async () => false)).toBeNull();
	});

	it('shelters flat ground behind a ridge only at ridge scale', async () => {
		// A 200 m wall, then flat ground to its east; wind from the west.
		const g = grid(160, 40, 25, (_, c) => (c < 60 ? 1000 : c < 64 ? 1200 : 1000));
		const near = sx(g, 270, 0, NEAR_M);
		const far = sx(halve(g), 270, NEAR_M, FAR_M);
		// 600 m behind the wall: beyond the near search, inside the far one.
		const c = 64 + 24;
		expect(near[20 * 160 + c]).toBeCloseTo(0, 5);
		expect(far[10 * 80 + c / 2]).toBeGreaterThan(12);
		const e = (await windEffect(g, [0, 0, 0, 0, 0, 0, 1, 0]))!;
		expect(e[20 * 160 + c]).toBeGreaterThan(0.2);
		expect(e[20 * 160 + 30]).toBeCloseTo(0, 5); // open flat ground upwind of it
	});

	it('weights the sectors that matter', () => {
		const w = windWeights([0, 0.02, 0, 0, 0, 0.6, 0.38, 0]);
		expect(w.map((s) => s.azimuth)).toEqual([225, 270]);
		expect(w[0].weight + w[1].weight).toBeCloseTo(1);
		expect(windWeights(Array(8).fill(0))).toEqual([]);
	});

	it('moves nothing below the thresholds and more with wind and snow', () => {
		const base = { minSnowCm: 2, minWindKmh: 15 };
		expect(transport({ ...base, snowCm: 1, meanKmh: 60 })).toBe(0);
		expect(transport({ ...base, snowCm: 30, meanKmh: 10 })).toBe(0);
		expect(transport({ ...base, snowCm: 30, meanKmh: null })).toBe(0);
		const light = transport({ ...base, snowCm: 3, meanKmh: 18 });
		const strong = transport({ ...base, snowCm: 30, meanKmh: 60 });
		expect(light).toBeGreaterThan(0.15);
		expect(light).toBeLessThan(0.4);
		expect(strong).toBe(1);
	});

	it('paints loaded and scoured in different colours and leaves the slight clear', () => {
		const px = paintWind(Float32Array.from([1, -1, 0.05, 1]), 0.8);
		expect([px[0], px[1], px[2]]).toEqual([0x1b, 0x6f, 0x9c]);
		expect([px[4], px[5], px[6]]).toEqual([0xb5, 0x65, 0x1d]);
		expect(px[11]).toBe(0);
		expect(px[3]).toBe(255);
		// A slight event is a faint wash.
		expect(paintWind(Float32Array.from([1]), 0.25)[3]).toBeLessThan(100);
		expect(paintWind(Float32Array.from([1]), 0.05)[3]).toBe(0);
		expect(windWord(0.6)).toBe('Likely loaded');
		expect(windWord(-0.2)).toBe('Somewhat scoured');
		expect(windWord(0.02)).toBe('Little wind effect');
	});
});
