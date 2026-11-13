import { expect, test, type Page } from '@playwright/test';
import type { OverviewRow } from '../src/lib/types.gen';

// The overview comes from the page, not a service worker's cache, so it can be replaced.
test.use({ serviceWorkers: 'block' });

/** Serve an overview where one location storms twice inside another's longer storm:
 *  A snows days 1–2 and 4–5, B snows days 1–5, so all three storms make one cycle. */
async function twiceStorming(page: Page) {
	await page.route('**/api/overview', async (route) => {
		const res = await route.fetch();
		const rows = (await res.json()) as OverviewRow[];
		const live = rows.filter((r) => r.run_id != null && r.periods?.length);
		const [a, b] = live;
		const dates = [...new Set((a.periods ?? []).map((p) => p.date))].sort().slice(0, 6);
		const A = [3, 3, 0, 4, 4, 0];
		const B = [2, 2, 2, 2, 2, 0];
		for (const r of live)
			for (const p of r.periods ?? []) {
				const i = dates.indexOf(p.date);
				const day = i < 0 ? 0 : r === a ? A[i] : r === b ? B[i] : 0;
				// A storm is a run of snowy periods, so the day's snow is shared by its periods
				// (day and night) rather than leaving a dry night that would split it.
				const n = r.periods!.filter((q) => q.date === p.date).length;
				p.snow_cm = day / n;
				p.ptype = 'snow';
			}
		await route.fulfill({ response: res, json: rows });
	});
}

test('the Calendar shows a location that storms twice in one cycle', async ({ page }) => {
	const errors: string[] = [];
	page.on('pageerror', (e) => errors.push(e.message));
	await twiceStorming(page);
	await page.goto('/calendar');
	await expect(page.locator('main')).not.toContainText('Loading…', { timeout: 10_000 });
	await expect(page.getByRole('heading', { name: 'Something went wrong' })).toHaveCount(0);
	// One storm, opened in its sheet: each location listed once.
	const storm = page.locator('main button.sbtn, main button.srow').first();
	await storm.click();
	const dialog = page.getByRole('dialog');
	await expect(dialog).toBeVisible();
	await expect(dialog).toContainText('2 locations');
	expect(errors).toEqual([]);
});
