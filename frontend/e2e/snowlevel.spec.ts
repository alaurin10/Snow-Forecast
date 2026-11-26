// The snow level as rain, mix or snow (docs/MAP-PLAN.md, "Snow level as rain, mix or
// snow"): drawn from numbers with a smooth slider, and a key of three colours. The e2e
// server's snow level frames sit on a made-up ground (e2e/precip_fixture.py).
import { expect, test } from '@playwright/test';

test('the snow level shows snow, mix or rain at the ground, with a smooth slider', async ({
	page
}) => {
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(String(e)));
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await page.addInitScript(() => localStorage.setItem('sw.mapWeather', 'snowlevel'));
	await page.goto('/map?loc=crystal', { waitUntil: 'networkidle' });
	const slider = page.getByRole('slider', { name: 'Time' });
	await expect(slider).toBeVisible({ timeout: 30_000 });
	// Drawn from numbers: the slider runs freely between the 3-hourly frames.
	await expect(slider).toHaveAttribute('step', '0.01');
	const key = page.getByLabel('Key');
	await expect(key).toContainText('Snow');
	await expect(key).toContainText('Mix');
	await expect(key).toContainText('Rain');
	await slider.evaluate((el: HTMLInputElement) => {
		el.value = el.max;
		el.dispatchEvent(new Event('input', { bubbles: true }));
	});
	await expect(page.getByText(/^forecast · in /)).toBeVisible();
	expect(errors).toEqual([]);
});
