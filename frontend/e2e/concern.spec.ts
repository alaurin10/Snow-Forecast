// The map's experimental concern index: open to every visitor (there are no visitor
// accounts), but never drawn before this browser has accepted its warning, and the
// answer is remembered here.
import { expect, test, type Page } from '@playwright/test';

const CAPTION = 'Experimental estimate from the bulletin and terrain shape. Not a forecast.';

async function openLayers(page: Page) {
	await page.getByRole('button', { name: 'Layers' }).click();
	return page.getByRole('group', { name: 'Terrain overlay' });
}

test('the concern index asks first, and remembers the answer', async ({ page }) => {
	// A visitor, not signed in.
	expect((await page.request.get('/api/map/concern')).status()).toBe(200);
	await page.goto('/map', { waitUntil: 'networkidle' });
	const overlays = await openLayers(page);
	const none = overlays.getByRole('button', { name: 'None' });
	const concern = overlays.getByRole('button', { name: 'Concern index (experimental)' });
	await expect(concern).toBeVisible();

	// Chosen: the warning, with the fixed caption, and the layer not on yet.
	await concern.click();
	const ack = page.getByRole('alertdialog', { name: 'Concern index (experimental)' });
	await expect(ack).toBeVisible();
	await expect(ack).toContainText(CAPTION);
	await expect(ack).toContainText("Doesn't show runouts or slopes above you.");
	await expect(page.getByRole('region', { name: 'Concern index' })).toHaveCount(0);
	// It has the focus, and Tab stays inside it.
	await expect(ack).toBeFocused();
	for (let i = 0; i < 5; i++) await page.keyboard.press('Tab');
	expect(await page.evaluate(() => !!document.activeElement?.closest('[role=alertdialog]'))).toBe(
		true
	);

	// Escape is Cancel: no layer, and nothing remembered.
	await page.keyboard.press('Escape');
	await expect(ack).toHaveCount(0);
	await expect(none).toHaveAttribute('aria-pressed', 'true');
	expect(await page.evaluate(() => localStorage.getItem('sw.concernAck'))).toBeNull();

	// So is the Cancel button.
	await concern.click();
	await ack.getByRole('button', { name: 'Cancel' }).click();
	await expect(ack).toHaveCount(0);
	await expect(none).toHaveAttribute('aria-pressed', 'true');

	// Accepted: the layer's controls, with the caption, and the answer kept.
	await concern.click();
	await ack.getByRole('button', { name: 'I understand' }).click();
	await expect(ack).toHaveCount(0);
	await expect(concern).toHaveAttribute('aria-pressed', 'true');
	await page.getByRole('button', { name: 'Done' }).click();
	const controls = page.getByRole('region', { name: 'Concern index' });
	await expect(controls).toBeVisible();
	await expect(controls).toContainText(CAPTION);
	await expect(controls).toContainText('No avalanche forecast zone here.');
	expect(await page.evaluate(() => localStorage.getItem('sw.concernAck'))).toBe('1');

	// Next visit in this browser: straight to the layer, no second warning.
	await page.reload({ waitUntil: 'networkidle' });
	await expect(page.getByRole('region', { name: 'Concern index' })).toBeVisible();
	await expect(ack).toHaveCount(0);
	// Switched off and on again: still no second warning.
	const again = await openLayers(page);
	await again.getByRole('button', { name: 'None' }).click();
	await again.getByRole('button', { name: 'Concern index (experimental)' }).click();
	await expect(ack).toHaveCount(0);
});

test('another browser is asked again', async ({ browser }) => {
	const context = await browser.newContext();
	const page = await context.newPage();
	await page.addInitScript(() => localStorage.setItem('sw.mapOverlay', 'concern'));
	await page.goto('/map', { waitUntil: 'networkidle' });
	// The layer was chosen here, but this browser never accepted the warning.
	await expect(
		page.getByRole('alertdialog', { name: 'Concern index (experimental)' })
	).toBeVisible();
	await expect(page.getByRole('region', { name: 'Concern index' })).toHaveCount(0);
	await context.close();
});
