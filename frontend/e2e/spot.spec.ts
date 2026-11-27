// Forecasts anywhere (docs/OPEN-METEO-PLAN.md, milestone 2): a tap on the map, then "Full
// forecast here", opens the spot's page, at 380 px and on a desktop, light and dark. The
// e2e API makes spots from the fixtures through a stand-in forecast server
// (e2e/openmeteo_fixture.py), near Whistler so no US alerts are asked for.
import { expect, test, type Page } from '@playwright/test';

const MAP = '/map?lat=50.12&lon=-122.95';

function watch(page: Page): string[] {
	const problems: string[] = [];
	page.on('pageerror', (e) => problems.push(`error: ${e.message}`));
	return problems;
}

/** Tap the middle of the map until the spot's panel opens. */
async function tapSpot(page: Page) {
	const canvas = page.locator('.maplibregl-canvas');
	await expect(canvas).toBeVisible({ timeout: 20_000 });
	const panel = page.getByRole('dialog', { name: 'This spot', exact: true });
	await expect(async () => {
		const b = (await canvas.boundingBox())!;
		await page.mouse.click(b.x + b.width / 2, b.y + b.height * 0.4);
		await expect(panel).toBeVisible({ timeout: 1500 });
	}).toPass({ timeout: 20_000 });
	return panel;
}

async function noSideways(page: Page) {
	const sideways = await page.evaluate(
		() => document.documentElement.scrollWidth - document.documentElement.clientWidth
	);
	expect(sideways).toBeLessThanOrEqual(1);
}

for (const theme of ['light', 'dark'] as const) {
	test(`map tap → Full forecast here → the spot's page (${theme})`, async ({ page }, info) => {
		test.slow();
		const problems = watch(page);
		if (info.project.name === 'phone') await page.setViewportSize({ width: 380, height: 800 });
		await page.addInitScript((t) => localStorage.setItem('sw.theme', t), theme);
		await page.goto(MAP, { waitUntil: 'networkidle' });
		const panel = await tapSpot(page);
		await panel.getByRole('link', { name: 'Full forecast here' }).click();

		await expect(page).toHaveURL(/\/spot\?lat=50\.\d{3}&lon=-122\.\d{3}/);
		await expect(page.getByText('Forecast for this spot, made now.')).toBeVisible({
			timeout: 15_000
		});
		await expect(page.locator('h1')).toContainText(/Whistler|° N/);
		await expect(page.locator('.spotnote .tag')).toHaveText('This spot');
		// The stand-in ground rises to the north: the spot is the middle band, chosen at once.
		await expect(page.locator('.spotband[aria-pressed="true"]').first()).toBeVisible();
		const tabs = page.getByRole('tablist', { name: 'Sections' });
		await expect(tabs.getByRole('tab')).toHaveText([
			'Forecast',
			'Backcountry',
			'Confidence',
			'Observed'
		]);
		await expect(page.getByText('Day by day').first()).toBeVisible();
		await noSideways(page);

		// No trend or scorecard for a spot; no snow station of its own.
		await tabs.getByRole('tab', { name: 'Confidence' }).click();
		await expect(page.getByText('How sure is this forecast?')).toBeVisible();
		await expect(page.getByText('How the forecast has changed')).toHaveCount(0);
		await tabs.getByRole('tab', { name: 'Observed' }).click();
		await expect(page.getByText('has no snow station of its own')).toBeVisible();
		await noSideways(page);

		// It's on the Overview's recent spots now.
		await page.goto('/', { waitUntil: 'networkidle' });
		await expect(page.getByRole('heading', { name: 'Recent spots' })).toBeVisible();
		expect(problems).toEqual([]);
	});
}

test('a right-click on the map opens the full forecast there', async ({ page }, info) => {
	test.skip(info.project.name === 'phone', 'right-click is for a mouse');
	test.slow();
	await page.goto(MAP, { waitUntil: 'networkidle' });
	const canvas = page.locator('.maplibregl-canvas');
	await expect(canvas).toBeVisible({ timeout: 20_000 });
	const b = (await canvas.boundingBox())!;
	await page.mouse.click(b.x + b.width / 2, b.y + b.height / 2, { button: 'right' });
	await expect(page).toHaveURL(/\/spot\?lat=/, { timeout: 15_000 });
	await expect(page.getByText('Forecast for this spot, made now.')).toBeVisible({
		timeout: 15_000
	});
});

test('a spot outside the US and Canada says so', async ({ page }) => {
	await page.goto('/spot?lat=31&lon=-110', { waitUntil: 'networkidle' });
	await expect(page.getByRole('heading', { name: 'No forecast here' })).toBeVisible();
	await expect(page.getByText('Forecasts anywhere cover the US and Canada')).toBeVisible();
});
