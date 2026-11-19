// The Recent satellite base: chosen in the Layers sheet, its controls say what's shown,
// and the choices are kept in this browser.
import { expect, test } from '@playwright/test';

test('recent satellite can be chosen, and is remembered', async ({ page }) => {
	const res = await page.request.get('/api/sat');
	expect(res.status()).toBe(200);
	await page.goto('/map', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Layers' }).click();
	const bases = page.getByRole('group', { name: 'Base map', exact: true });
	const recent = bases.getByRole('button', { name: 'Recent satellite' });
	await recent.click();
	await expect(recent).toHaveAttribute('aria-pressed', 'true');
	await page
		.getByRole('dialog', { name: 'Map layers' })
		.getByRole('button', { name: 'Close' })
		.click();

	const controls = page.getByRole('region', { name: 'Recent satellite' });
	await expect(controls).toBeVisible();
	await expect(controls).toContainText('10 m Sentinel-2 views are kept near saved locations.');
	await controls.getByRole('button', { name: 'Snow vs cloud' }).click();
	await controls.getByRole('button', { name: 'About this view' }).click();
	await expect(controls).toContainText('Snow shows cyan, cloud white.');

	await page.reload({ waitUntil: 'networkidle' });
	await expect(page.getByRole('region', { name: 'Recent satellite' })).toBeVisible();
	expect(
		await page.evaluate(() => [
			localStorage.getItem('sw.mapBase'),
			localStorage.getItem('sw.satBands')
		])
	).toEqual(['recent', 'snow']);
	await expect(
		page
			.getByRole('region', { name: 'Recent satellite' })
			.getByRole('button', { name: 'Snow vs cloud' })
	).toHaveAttribute('aria-pressed', 'true');
});

test('the Base pill switches the base map, and the row of tabs fits a phone', async ({
	browser
}, info) => {
	test.skip(info.project.name !== 'phone', 'one run is enough');
	for (const width of [320, 375]) {
		const ctx = await browser.newContext({ viewport: { width, height: 700 }, hasTouch: true });
		await ctx.addInitScript(() => {
			localStorage.setItem('sw.mapOverlay', 'bands');
			localStorage.setItem('sw.mapWeather', 'totals');
		});
		const page = await ctx.newPage();
		await page.goto('/map', { waitUntil: 'networkidle' });
		const tabs = page.getByRole('group', { name: 'Map controls' });
		await tabs.getByRole('button', { name: /^Base/ }).click();
		const bases = page.getByRole('group', { name: 'Base map type' });
		await bases.getByRole('button', { name: 'Satellite (detailed, undated)' }).click();
		await expect(tabs.getByRole('button', { name: /^Base/ })).toContainText('Satellite');
		// Recent opens its own controls under the base types.
		await bases.getByRole('button', { name: 'Recent satellite' }).click();
		await expect(page.getByRole('region', { name: 'Recent satellite' })).toBeVisible();
		expect(await page.evaluate(() => localStorage.getItem('sw.mapBase'))).toBe('recent');
		// Base, Terrain and Weather in one row, nothing scrolled out of sight.
		const { sw, cw, left, right } = await tabs.evaluate((el) => {
			const r = el.getBoundingClientRect();
			return { sw: el.scrollWidth, cw: el.clientWidth, left: r.left, right: r.right };
		});
		expect(sw).toBeLessThanOrEqual(cw + 1);
		expect(left).toBeGreaterThanOrEqual(0);
		expect(right).toBeLessThanOrEqual(width);
		await ctx.close();
	}
});
