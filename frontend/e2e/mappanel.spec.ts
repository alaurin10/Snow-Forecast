// Map taps open one panel in one place (docs/APP-NOTES-PLAN.md, milestone 3): a snow
// station, a glacier and bare ground each open the map panel at the same spot on screen,
// on the most specific thing under the tap, with chips for the rest; a right-click goes
// straight to the spot's numbers. The fixtures (e2e/serve.sh) put a station 0.02° east of
// Rainy Pass and a glacier just south of it.
import { expect, test, type Page } from '@playwright/test';

/** Pixels per degree of longitude at the zoom a location opens at (11.5, 512 px tiles). */
const PX_LON = (512 * 2 ** 11.5) / 360;
/** Pixels per degree of latitude there (Mercator, at 48.51° N). */
const PX_LAT = PX_LON / Math.cos((48.511 * Math.PI) / 180);

/** Rainy Pass's pin on screen, once the map has stopped moving. */
async function pin(page: Page) {
	const el = page.getByRole('button', { name: /^Heather–Maple \/ Rainy Pass:/ });
	let last: { x: number; y: number } | null = null;
	for (let i = 0; i < 60; i++) {
		const b = await el.boundingBox();
		const c = b && { x: b.x + b.width / 2, y: b.y + b.height / 2 };
		if (c && last && Math.abs(c.x - last.x) < 0.5 && Math.abs(c.y - last.y) < 0.5) return c;
		last = c;
		await page.waitForTimeout(120);
	}
	throw new Error('the map kept moving');
}

async function panelBox(page: Page) {
	const panel = page.locator('[data-map-panel]');
	// The phone sheet eases to its height.
	await page.waitForTimeout(400);
	const b = (await panel.boundingBox())!;
	return { x: Math.round(b.x), y: Math.round(b.y), width: Math.round(b.width), h: b.height };
}

test('a station, a glacier and bare ground open the same panel in the same place', async ({
	page
}, info) => {
	await page.addInitScript(() => localStorage.setItem('sw.mapFeatures', 'stations,glaciers'));
	await page.goto('/map?loc=rainy', { waitUntil: 'networkidle' });
	const desktop = info.project.name === 'desktop';

	// The location's popup is open: the first tap only closes it.
	let p = await pin(page);
	await page.mouse.click(p.x - 0.02 * PX_LON, p.y);

	// A station: its own panel, with nothing else here but the spot.
	p = await pin(page);
	await expect(async () => {
		await page.mouse.click(p.x + 0.02 * PX_LON, p.y);
		await expect(page.getByRole('dialog', { name: 'Rainy Pass test station' })).toBeVisible({
			timeout: 1000
		});
	}).toPass({ timeout: 15_000 });
	const station = page.getByRole('dialog', { name: 'Rainy Pass test station' });
	await expect(station).toContainText('Snow station');
	await expect(station).toContainText('Snow depth');
	const first = await panelBox(page);
	if (desktop) {
		// Docked to the right edge.
		const vp = page.viewportSize()!;
		expect(first.x + first.width).toBeGreaterThan(vp.width - 20);
		expect(first.y).toBeLessThan(20);
	}

	// A glacier: its area from the whole outline, and the spot one chip away.
	p = await pin(page);
	await page.mouse.click(p.x, p.y + 0.014 * PX_LAT);
	const glacier = page.getByRole('dialog', { name: 'Test Glacier' });
	await expect(glacier).toBeVisible();
	await expect(glacier).toContainText('Glacier');
	// 0.02° × 0.008° at 48.5° N: about 1.5 km × 0.9 km.
	await expect(glacier).toContainText(/1\.3 km²|1\.2 km²|3\d\d acres/);
	expect(await panelBox(page)).toMatchObject(
		desktop ? { x: first.x, y: first.y, width: first.width } : first
	);
	const spotChip = glacier.getByRole('button', { name: 'This spot' });
	if (await spotChip.count()) {
		await spotChip.click();
		await expect(page.getByRole('dialog', { name: 'This spot' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Glacier', pressed: false })).toBeVisible();
	}

	// Bare ground: the spot itself, terrain and weather, in the same place.
	p = await pin(page);
	await page.mouse.click(p.x - 0.02 * PX_LON, p.y);
	const spot = page.getByRole('dialog', { name: 'This spot' });
	await expect(spot).toBeVisible();
	await expect(spot.getByRole('region', { name: 'Terrain' })).toBeVisible();
	await expect(spot.getByRole('region', { name: 'Snow and weather' })).toBeVisible();
	await expect(spot.getByText('About these numbers')).toBeVisible();
	expect(await panelBox(page)).toMatchObject(
		desktop ? { x: first.x, y: first.y, width: first.width } : first
	);

	await page.keyboard.press('Escape');
	await expect(page.locator('[data-map-panel]')).toHaveCount(0);

	if (desktop) {
		// A right-click on the glacier goes straight to the spot.
		p = await pin(page);
		await page.mouse.click(p.x, p.y + 0.014 * PX_LAT, { button: 'right' });
		await expect(page.getByRole('dialog', { name: 'This spot' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Glacier' })).toHaveCount(0);
	}
});

test('phones: the tab bar is icons only on the map, at the same height', async ({ page }, info) => {
	test.skip(info.project.name !== 'phone', 'the tab bar is for phones and tablets');
	const bar = page.getByRole('navigation', { name: 'Main' });
	await page.goto('/', { waitUntil: 'networkidle' });
	const wide = (await bar.boundingBox())!;
	await expect(bar.getByText('Overview')).toBeVisible();
	await page.goto('/map', { waitUntil: 'networkidle' });
	await expect(bar).toHaveClass(/compact/);
	await expect(bar.getByText('Overview')).toBeHidden();
	await expect.poll(async () => (await bar.boundingBox())!.width).toBeLessThan(wide.width - 100);
	expect(Math.round((await bar.boundingBox())!.height)).toBe(Math.round(wide.height));
});
