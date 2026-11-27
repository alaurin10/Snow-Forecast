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
		// The open panel starts the spot's forecast before the button is pressed.
		const early = page.waitForRequest(/\/api\/spot\?.*early=1/, { timeout: 20_000 });
		const panel = await tapSpot(page);
		await early;
		await panel.getByRole('link', { name: 'Full forecast here' }).click();

		await expect(page).toHaveURL(/\/spot\?lat=50\.\d{3}&lon=-122\.\d{3}/);
		await expect(page.getByText('Forecast for this spot, made now.')).toBeVisible({
			timeout: 15_000
		});
		// Named after the terrain: a peak (from the map's label tiles), a saved location or
		// the coordinates.
		await expect(page.locator('h1')).toContainText(/ of |° N|\w/);
		// One elevation, the spot's own, shown where the picker would be; no elevation
		// picker, no base/mid/summit table.
		await expect(page.locator('.spotelev')).toContainText('4,900 ft');
		await expect(page.getByRole('group', { name: /^Elevation/ })).toHaveCount(0);
		await expect(page.getByRole('heading', { name: 'Base, mid and summit' })).toHaveCount(0);
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

		// On a phone, the header's back arrow goes to the map.
		if (info.project.name === 'phone') {
			await page.getByRole('link', { name: 'Back to the map' }).click();
			await expect(page).toHaveURL(/\/map\?lat=/);
		}

		// It's on the Overview's recent spots now.
		await page.goto('/', { waitUntil: 'networkidle' });
		await expect(page.getByRole('heading', { name: 'Recent spots' })).toBeVisible();
		expect(problems).toEqual([]);
	});
}

test('back from a spot, the map is where it was', async ({ page }) => {
	test.slow();
	// Open the map over Washington, then move it to Whistler and in close.
	await page.goto('/map', { waitUntil: 'networkidle' });
	await page.goto(MAP, { waitUntil: 'networkidle' });
	const whistler = page.getByRole('button', { name: /^Whistler/ });
	// Pan it with the keyboard (the map would open on this point anyway), then let the
	// view be kept.
	const start = (await whistler.boundingBox())!;
	await page.locator('.maplibregl-canvas').focus();
	await expect(async () => {
		await page.keyboard.press('ArrowLeft');
		await page.waitForTimeout(400);
		const moved = (await whistler.boundingBox())!;
		expect(moved.x - start.x).toBeGreaterThan(150);
	}).toPass({ timeout: 15_000 });
	await page.waitForTimeout(1200);
	const before = await whistler.boundingBox();
	expect(before).not.toBeNull();
	const panel = await tapSpot(page);
	await panel.getByRole('link', { name: 'Full forecast here' }).click();
	await expect(page.getByText('Forecast for this spot, made now.')).toBeVisible({
		timeout: 15_000
	});
	await page.goBack();
	await expect(page).toHaveURL(/\/map(\?|$)/);
	// The spot just opened has its panel open again, for context.
	await expect(page.getByRole('dialog', { name: 'This spot', exact: true })).toBeVisible({
		timeout: 15_000
	});
	// The same view: Whistler's pin where it was, not the opening view over Washington.
	await expect(async () => {
		const after = (await whistler.boundingBox())!;
		expect(Math.abs(after.x - before!.x)).toBeLessThan(8);
		expect(Math.abs(after.y - before!.y)).toBeLessThan(8);
	}).toPass({ timeout: 15_000 });
});

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

test('only the owner can save a spot, placing its low and high points in Manage', async ({
	page
}, info) => {
	test.skip(info.project.name === 'phone', 'one screen size is enough');
	const spot = '/spot?lat=50.120&lon=-122.950';
	await page.goto(spot, { waitUntil: 'networkidle' });
	await expect(page.getByText('Forecast for this spot, made now.')).toBeVisible({
		timeout: 15_000
	});
	await expect(page.getByRole('link', { name: 'Save as location' })).toHaveCount(0);
	// Signed in (the page's requests share the browser's cookies).
	const r = await page.request.post('/api/auth/login', {
		data: { password: 'e2e-owner-password' },
		headers: { Origin: 'http://localhost:8019' }
	});
	expect(r.ok()).toBe(true);
	await page.goto(spot, { waitUntil: 'networkidle' });
	await page.getByRole('link', { name: 'Save as location' }).click();
	await expect(page.getByRole('heading', { name: 'Add a backcountry zone' })).toBeVisible();
	await expect(page.getByText('The spot is the mid pin.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Mid (optional) ✓' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Trailhead', exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	expect(await page.getByLabel('Name').inputValue()).not.toBe('');
});

test('a spot outside the US and Canada says so', async ({ page }) => {
	await page.goto('/spot?lat=31&lon=-110', { waitUntil: 'networkidle' });
	await expect(page.getByRole('heading', { name: 'No forecast here' })).toBeVisible();
	await expect(page.getByText('Forecasts anywhere cover the US and Canada')).toBeVisible();
});
