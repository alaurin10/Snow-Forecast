// The radar drawn from numbers on the graphics chip (src/lib/map/precip/, docs/RADAR-PLAN.md
// M2). The first attempt at this (reverted in b2d345a) stopped redrawing in 3D after a
// frame change, disagreed between flat and 3D, and stayed blank after the graphics were
// lost: each is checked here. The e2e server's frames (e2e/precip_fixture.py) carry
// numbers, so the radar takes this path.
import { createHash } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';

async function open(page: Page) {
	// No base map: the radar is what changes on screen (tiles arriving would change it too).
	await page.route('**/api/tiles/**', (r) => r.abort());
	await page.addInitScript(() => localStorage.setItem('sw.mapWeather', 'radar'));
	await page.goto('/map', { waitUntil: 'networkidle' });
	const slider = page.getByRole('slider', { name: 'Time' });
	// The timeline may take a while on a busy machine.
	await expect(slider).toBeVisible({ timeout: 30_000 });
	const pause = page.getByRole('button', { name: 'Pause' });
	if (await pause.count()) await pause.click();
	// Days 11–16 are fetched once the slider goes past the "Less certain" mark: once to the
	// end and back, so every frame is wanted.
	await slide(page, Number(await slider.getAttribute('max')));
	await slide(page, 0);
	// Every frame on hand: the track shows no "still loading" stripes.
	await expect
		.poll(() => slider.evaluate((el) => getComputedStyle(el).getPropertyValue('--buffer').trim()), {
			timeout: 20_000
		})
		.toBe('none');
	return slider;
}

async function slide(page: Page, v: number) {
	await page.getByRole('slider', { name: 'Time' }).evaluate((el: HTMLInputElement, v) => {
		el.value = String(v);
		el.dispatchEvent(new Event('input', { bubbles: true }));
	}, v);
	await page.waitForTimeout(400);
}

/** The map's pixels as a hash (the map canvas only: the controls don't count), once they
 *  have stopped changing (elevation tiles may still be arriving in 3D). */
async function look(page: Page): Promise<string> {
	const canvas = page.locator('canvas.maplibregl-canvas');
	const hash = async () =>
		createHash('sha1')
			.update(await canvas.screenshot({ timeout: 60_000 }))
			.digest('hex');
	let last = await hash();
	for (let i = 0; i < 8; i++) {
		await page.waitForTimeout(300);
		const now = await hash();
		if (now === last) return now;
		last = now;
	}
	return last;
}

/** The share of pixels that differ clearly between two screenshots (decoded in the page). */
async function differ(page: Page, a: Buffer, b: Buffer): Promise<number> {
	return page.evaluate(
		async ([a, b]) => {
			const read = async (b64: string) => {
				const img = new Image();
				img.src = `data:image/png;base64,${b64}`;
				await img.decode();
				const c = document.createElement('canvas');
				c.width = img.width;
				c.height = img.height;
				const ctx = c.getContext('2d')!;
				ctx.drawImage(img, 0, 0);
				return ctx.getImageData(0, 0, c.width, c.height).data;
			};
			const [x, y] = await Promise.all([read(a), read(b)]);
			let n = 0;
			for (let i = 0; i < x.length; i += 4)
				if (Math.max(...[0, 1, 2].map((k) => Math.abs(x[i + k] - y[i + k]))) > 16) n++;
			return n / (x.length / 4);
		},
		[a.toString('base64'), b.toString('base64')]
	);
}

test('the slider moves the radar freely, in steps of less than a frame', async ({ page }) => {
	// A dozen full-screen screenshots at a phone's pixel density: more than the default 30 s
	// on a slow machine.
	test.setTimeout(90_000);
	const slider = await open(page);
	expect(Number(await slider.getAttribute('step'))).toBeLessThan(1);
	const seen = new Set<string>();
	const canvas = page.locator('canvas.maplibregl-canvas');
	let at2: Buffer | null = null;
	for (const v of [2, 2.5, 3, 6, 9]) {
		await slide(page, v);
		seen.add(await look(page));
		if (v === 2) at2 = await canvas.screenshot();
	}
	// Between two frames is neither of them.
	expect(seen.size).toBe(5);
	// Back on a frame: the same picture (give or take a pixel's rounding).
	await slide(page, 2);
	await look(page);
	expect(await differ(page, at2!, await canvas.screenshot())).toBeLessThan(0.002);
});

// One run, at the desktop size, on its own (the solo project, playwright.config.ts): 3D is
// slow in software and takes every core.
const solo = { tag: '@solo' };

test('in 3D every frame change is drawn, and comes back the same', solo, async ({ page }) => {
	test.setTimeout(180_000);
	await open(page);
	await page.getByRole('button', { name: '3D terrain' }).click();
	await page.waitForTimeout(2500);
	const canvas = page.locator('canvas.maplibregl-canvas');
	const hashes: string[] = [];
	let at4: Buffer | null = null;
	for (const v of [1, 4, 7, 10, 13, 16]) {
		await slide(page, v);
		hashes.push(await look(page));
		if (v === 4) at4 = await canvas.screenshot({ timeout: 60_000 });
	}
	expect(new Set(hashes).size).toBe(6);
	// Back to a frame: the same picture (give or take elevation tiles settling).
	await slide(page, 4);
	await look(page);
	expect(await differ(page, at4!, await canvas.screenshot({ timeout: 60_000 }))).toBeLessThan(0.01);
});

test('the radar comes back after the graphics are lost', async ({ page }, info) => {
	test.skip(info.project.name !== 'desktop', 'one run is enough');
	test.setTimeout(90_000);
	await open(page);
	await slide(page, 5);
	await look(page);
	const canvas = page.locator('canvas.maplibregl-canvas');
	const before = await canvas.screenshot();
	await page.evaluate(async () => {
		const canvas = document.querySelector('canvas.maplibregl-canvas') as HTMLCanvasElement;
		const gl = canvas.getContext('webgl2')!;
		const lose = gl.getExtension('WEBGL_lose_context')!;
		lose.loseContext();
		await new Promise((r) => setTimeout(r, 300));
		lose.restoreContext();
	});
	// The style is rebuilt and every frame uploaded again: the same picture (give or take
	// a pixel's rounding).
	await expect
		.poll(async () => differ(page, before, await canvas.screenshot()), { timeout: 30_000 })
		.toBeLessThan(0.002);
});

test("radar's blind spots are filled from the forecast, or left out", async ({ page }) => {
	// The e2e frames say radar doesn't see round the cell in the north-east of the box
	// (e2e/precip_fixture.py): drawn hatched by default, gone with "Radar only".
	test.setTimeout(90_000);
	await open(page);
	// Zoomed out so the whole box is on screen at any width.
	const canvas = page.locator('canvas.maplibregl-canvas');
	await canvas.focus();
	for (let i = 0; i < 2; i++) {
		await page.keyboard.press('Minus');
		await page.waitForTimeout(600);
	}
	await look(page);
	const filled = await canvas.screenshot();
	await page.getByRole('button', { name: 'Layers', exact: true }).click();
	await page.getByRole('button', { name: 'Radar only' }).click();
	await page.getByRole('button', { name: 'Layers', exact: true }).click();
	await look(page);
	const radarOnly = await canvas.screenshot();
	expect(await differ(page, filled, radarOnly)).toBeGreaterThan(0.002);
	expect(await page.evaluate(() => localStorage.getItem('sw.mapRadarGaps'))).toBe('off');
	// And back.
	await page.getByRole('button', { name: 'Layers', exact: true }).click();
	await page.getByRole('button', { name: 'Fill gaps' }).click();
	await page.getByRole('button', { name: 'Layers', exact: true }).click();
	await look(page);
	expect(await differ(page, filled, await canvas.screenshot())).toBeLessThan(0.002);
});
