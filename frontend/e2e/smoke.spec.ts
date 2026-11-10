import { expect, test, type Page } from '@playwright/test';

const PAGES = [
	'/',
	'/calendar',
	'/map',
	'/more',
	'/about',
	'/status',
	'/admin',
	'/location/whistler',
	'/location/rainy',
	'/location/crystal'
];

/** Page errors and CSP violations, collected while the test runs. */
function watch(page: Page): string[] {
	const problems: string[] = [];
	page.on('pageerror', (e) => problems.push(`error: ${e.message}`));
	page.on('console', (m) => {
		if (m.type() === 'error' && /Content Security Policy|Refused to/.test(m.text()))
			problems.push(`csp: ${m.text()}`);
	});
	return problems;
}

for (const path of PAGES) {
	test(`${path} loads without errors or sideways scrolling`, async ({ page }) => {
		const problems = watch(page);
		const res = await page.goto(path, { waitUntil: 'networkidle' });
		expect(res?.status()).toBe(200);
		await expect(page.locator('main')).not.toBeEmpty();
		await expect(page.locator('main')).not.toContainText('Loading…', { timeout: 10_000 });
		const sideways = await page.evaluate(
			() => document.documentElement.scrollWidth - document.documentElement.clientWidth
		);
		expect(sideways).toBeLessThanOrEqual(1);
		expect(problems).toEqual([]);
	});
}

test('an unknown page and an unknown location say so', async ({ page }) => {
	await page.goto('/no-such-page');
	await expect(page.getByRole('heading', { name: 'There’s nothing here' })).toBeVisible();
	await page.goto('/location/nowhere');
	await expect(page.getByRole('heading', { name: 'No forecast here' })).toBeVisible();
});

test('owner sign-in: wrong password, then right, then sign out', async ({ page }) => {
	await page.goto('/admin');
	const password = page.getByLabel('Password');
	await password.fill('not-it');
	await page.getByRole('button', { name: 'Sign in' }).click();
	await expect(page.getByRole('alert')).toContainText('isn’t right');
	await password.fill('e2e-owner-password');
	await page.getByRole('button', { name: 'Sign in' }).click();
	await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
	await expect(page.locator('main')).toContainText('Whistler');
	await page.getByRole('button', { name: 'Sign out' }).click();
	await expect(page.getByLabel('Password')).toBeVisible();
});

test('the share sheet is a proper dialog', async ({ page }) => {
	await page.goto('/location/whistler');
	const share = page.getByRole('button', { name: /share/i }).first();
	await share.focus();
	await page.keyboard.press('Enter');
	const dialog = page.getByRole('dialog');
	await expect(dialog).toBeVisible();
	for (let i = 0; i < 15; i++) await page.keyboard.press('Tab');
	expect(await page.evaluate(() => !!document.activeElement?.closest('[role=dialog]'))).toBe(true);
	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0);
	await expect(share).toBeFocused();
});

test('responses carry the security headers', async ({ request }) => {
	const res = await request.get('/');
	const h = res.headers();
	expect(h['content-security-policy']).toContain("frame-ancestors 'none'");
	expect(h['x-content-type-options']).toBe('nosniff');
	const admin = await request.post('/api/admin/lookups/refresh');
	expect(admin.status()).toBe(401);
});
