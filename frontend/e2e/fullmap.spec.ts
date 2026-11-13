// Desktop: the map fills the whole window, the rail floats over it and folds to a
// button, and the choice is kept in this browser. Other pages keep the rail beside them.
import { expect, test } from '@playwright/test';

test('the desktop map fills the window and the rail folds', async ({ page }, info) => {
	test.skip(info.project.name !== 'desktop', 'the rail is desktop only');
	await page.goto('/map', { waitUntil: 'networkidle' });
	const box = await page.locator('.maplibregl-canvas').boundingBox();
	const vp = page.viewportSize()!;
	expect(box).toMatchObject({ x: 0, y: 0 });
	expect(Math.round(box!.width)).toBe(vp.width);
	expect(Math.round(box!.height)).toBe(vp.height);

	const rail = page.getByRole('complementary', { name: 'Navigation' });
	await expect(rail).toBeVisible();
	const toolsBefore = (await page.getByRole('button', { name: 'Layers' }).boundingBox())!.x;
	expect(toolsBefore).toBeGreaterThan(262);

	await page.getByRole('button', { name: 'Hide navigation' }).click();
	await expect(rail).toBeHidden();
	await expect(page.getByRole('button', { name: 'Show navigation' })).toBeVisible();
	await expect
		.poll(async () => (await page.getByRole('button', { name: 'Layers' }).boundingBox())!.x)
		.toBeLessThan(120);
	// The folded button heads the map's column of buttons: same left edge and width, and
	// the zoom buttons start under it.
	const fold = (await page.getByRole('button', { name: 'Show navigation' }).boundingBox())!;
	const zoom = (await page.getByRole('button', { name: 'Zoom in' }).boundingBox())!;
	expect(Math.abs(fold.x - zoom.x)).toBeLessThan(2);
	expect(Math.abs(fold.width - zoom.width)).toBeLessThan(2);
	expect(zoom.y).toBeGreaterThan(fold.y + fold.height);

	await page.reload({ waitUntil: 'networkidle' });
	await expect(page.getByRole('button', { name: 'Show navigation' })).toBeVisible();
	// Other pages keep the rail beside them, folded or not.
	await page.goto('/', { waitUntil: 'networkidle' });
	await expect(page.getByRole('complementary', { name: 'Navigation' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Hide navigation' })).toHaveCount(0);
	await page.goto('/map', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Show navigation' }).click();
	await expect(page.getByRole('complementary', { name: 'Navigation' })).toBeVisible();
});

test('the map opens flat, even after 3D was on', async ({ page }) => {
	await page.goto('/map', { waitUntil: 'networkidle' });
	const three = page.getByRole('button', { name: '3D terrain' });
	await expect(three).toHaveAttribute('aria-pressed', 'false');
	await three.click();
	await expect(three).toHaveAttribute('aria-pressed', 'true');
	await page.reload({ waitUntil: 'networkidle' });
	await expect(page.getByRole('button', { name: '3D terrain' })).toHaveAttribute(
		'aria-pressed',
		'false'
	);
});
