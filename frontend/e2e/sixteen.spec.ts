import { expect, test } from '@playwright/test';

// Milestone 4B: forecasts to 16 days (today and the next 15). The rebuilt fixtures reach
// about 15.4 days from their capture, and the app runs at that moment.

for (const scheme of ['light', 'dark'] as const) {
	test(`the chart offers 15 days, marked less certain twice (${scheme})`, async ({
		page,
		isMobile
	}) => {
		await page.emulateMedia({ colorScheme: scheme });
		await page.goto('/location/crystal');
		const ranges = page.getByRole('group', { name: 'Time range' }).first();
		await expect(ranges.getByRole('button')).toHaveCount(5);
		// On a phone the buttons read "1d … 15d"; their names stay whole words.
		await expect(ranges.getByRole('button', { name: '15 days' })).toHaveText(
			isMobile ? '15d' : '15 days'
		);
		await ranges.getByRole('button', { name: '15 days' }).click();
		// Two marks, 5 and 10 days out: the second adds a tick and label, not a veil.
		const marks = page.locator('.fc .conf');
		await expect(marks).toHaveCount(2);
		await expect(page.locator('.fc .conf2')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
		await expect(page.locator('.fc .conf span').first()).toHaveText('Less certain →');
		// Nothing pushes the page sideways.
		const sideways = await page.evaluate(
			() => document.documentElement.scrollWidth - document.documentElement.clientWidth
		);
		expect(sideways).toBeLessThanOrEqual(1);
	});
}

test('the 10-day view shows the second mark as a tick only', async ({ page }) => {
	await page.goto('/location/crystal');
	await page
		.getByRole('group', { name: 'Time range' })
		.first()
		.getByRole('button', { name: '10 days' })
		.click();
	// Its first bar starts at the next 6 AM or 6 PM, so 10 days out falls at the right edge
	// (or just past it): a tick there at most, never a second label.
	await expect(page.locator('.fc .conf')).not.toHaveCount(0);
	await expect(page.locator('.fc .conf2 span')).toHaveCount(0);
});

test('the day by day lists 16 days, without ratings past day 10', async ({ page, isMobile }) => {
	await page.goto('/location/crystal');
	await expect(page.getByText('Day by day').first()).toBeVisible();
	if (isMobile) {
		// The phone's list: one row per day, today and the next 15.
		await expect(page.locator('ul.days > li')).toHaveCount(16);
	} else {
		// The table: a header row and one per day; the last day has no rating badge.
		const rows = page.locator('[aria-label="Day by day"] [role="row"]');
		await expect(rows).toHaveCount(17);
		await expect(rows.last().locator('b')).toHaveCount(0);
	}
});

test('the Calendar shows 16 days; a phone scrolls them sideways', async ({ page, isMobile }) => {
	await page.goto('/calendar');
	await expect(page.locator('main')).not.toContainText('Loading…', { timeout: 10_000 });
	if (isMobile) {
		const rows = page.locator('.mrows');
		await expect(rows).toHaveClass(/wide/);
		await expect(page.locator('.mdgrid > span')).toHaveCount(16);
		// The rows scroll in their card, the page doesn't; the dates follow the rows.
		const sideways = await page.evaluate(
			() => document.documentElement.scrollWidth - document.documentElement.clientWidth
		);
		expect(sideways).toBeLessThanOrEqual(1);
		await rows.evaluate((el) => (el.scrollLeft = 100));
		await expect(page.locator('.mdgrid')).toHaveCSS('transform', /matrix\(1, 0, 0, 1, -100/);
		// Names stay in view.
		const name = page.locator('.mrows .mname a').first();
		const box = (await name.boundingBox())!;
		expect(box.x).toBeGreaterThanOrEqual(0);
	} else {
		await expect(page.locator('table.cal thead th.date')).toHaveCount(16);
	}
});

test('the Confidence tab has the chances for days 11–16', async ({ page }) => {
	await page.goto('/location/whistler');
	await page.getByRole('tab', { name: 'Confidence' }).click();
	await expect(page.getByRole('columnheader', { name: 'Days 11–16' })).toBeVisible();
	await expect(page.getByRole('columnheader', { name: '10-day total' })).toBeVisible();
});
