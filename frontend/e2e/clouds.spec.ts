// Clouds at their heights: the forecast cloud frames drawn from numbers, against the
// terrain when zoomed in (src/lib/map/precip/cloudlayer.ts), and the 3D clouds floating
// around each location (src/lib/map/clouds3d/). The e2e server's cloud frames carry a
// deck over the Cascades with its heights (e2e/precip_fixture.py); its locations have no
// cloud layers (the fixtures predate them), so the 3D clouds are given some here.
import { expect, test } from '@playwright/test';

test('zoomed in, forecast clouds are drawn at their height', async ({ page }) => {
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	// Less motion: the loop doesn't play by itself, so the slider stays where it's put.
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await page.addInitScript(() => localStorage.setItem('sw.mapWeather', 'clouds'));
	await page.goto('/map?loc=crystal', { waitUntil: 'networkidle' });
	const slider = page.getByRole('slider', { name: 'Time' });
	await expect(slider).toBeVisible({ timeout: 30_000 });
	// Frame 0 is the satellite picture; frame 1 the first forecast, which has heights.
	await slider.evaluate((el: HTMLInputElement) => {
		el.value = '1';
		el.dispatchEvent(new Event('input', { bubbles: true }));
	});
	await expect(page.getByText('forecast · in')).toBeVisible();
	await expect(page.getByText('at cloud height')).toBeVisible({ timeout: 15_000 });
	// Zoomed out (the map's own "-" key: phones have no zoom buttons), the cover alone.
	await page.locator('canvas.maplibregl-canvas').focus();
	for (let i = 0; i < 4; i++) {
		await page.keyboard.press('Minus');
		await page.waitForTimeout(400);
	}
	await expect(page.getByText('at cloud height')).toBeHidden({ timeout: 10_000 });
	expect(errors).toEqual([]);
});

test('3D clouds can be switched on under Show, and float around a location', async ({
	browser
}) => {
	// The service worker would answer the request itself, past the stand-in below.
	const ctx = await browser.newContext({ serviceWorkers: 'block' });
	const page = await ctx.newPage();
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	let asked = 0;
	const start = Math.floor(Date.now() / 3_600_000) * 3600 - 3 * 3600;
	await page.route('**/api/map/clouds', (route) => {
		asked++;
		return route.fulfill({
			json: {
				locations: [
					{
						id: 'crystal',
						name: 'Crystal Mountain',
						lat: 46.935,
						lon: -121.475,
						base_m: 1340,
						summit_m: 2130,
						generated_at: new Date().toISOString(),
						clouds: {
							model: 'gfs_seamless',
							start,
							step_h: 1,
							layers: Array.from({ length: 243 }, () => [[1500, 2400, 95]]),
							cover: Array(243).fill(95)
						}
					}
				]
			}
		});
	});
	await page.addInitScript(() => localStorage.setItem('sw.mapWeather', 'off'));
	await page.goto('/map?loc=crystal', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Layers' }).click();
	const tile = page.getByRole('button', { name: 'Clouds at their heights (3D)' });
	await expect(tile).toHaveAttribute('aria-pressed', 'false'); // off until chosen
	const canvas = page.locator('canvas.maplibregl-canvas');
	const before = await canvas.screenshot();
	await tile.click();
	await expect(tile).toHaveAttribute('aria-pressed', 'true');
	await expect.poll(() => asked).toBeGreaterThan(0);
	// Something is drawn over the map.
	await expect
		.poll(async () => Buffer.compare(await canvas.screenshot(), before) !== 0, { timeout: 15_000 })
		.toBe(true);
	// Off again: nothing more is asked for.
	await tile.click();
	await expect(tile).toHaveAttribute('aria-pressed', 'false');
	expect(errors).toEqual([]);
	await ctx.close();
});
