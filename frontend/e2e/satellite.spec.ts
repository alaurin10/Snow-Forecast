// The Recent satellite base: chosen in the Layers sheet, its controls say what's shown,
// and the choices are kept in this browser.
import { expect, test } from '@playwright/test';

test('recent satellite can be chosen, and is remembered', async ({ page }) => {
	const res = await page.request.get('/api/sat');
	expect(res.status()).toBe(200);
	await page.goto('/map', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Layers' }).click();
	const bases = page.getByRole('group', { name: 'Base map' });
	const recent = bases.getByRole('button', { name: 'Recent satellite' });
	await recent.click();
	await expect(recent).toHaveAttribute('aria-pressed', 'true');
	await page.getByRole('button', { name: 'Done' }).click();

	const controls = page.getByRole('region', { name: 'Recent satellite' });
	await expect(controls).toBeVisible();
	await expect(controls).toContainText('10 m Sentinel-2 views are kept near saved locations.');
	await controls.getByRole('button', { name: 'Snow vs cloud' }).click();
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
