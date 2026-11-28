import { expect, test, type Page } from '@playwright/test';

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

// ---- The map (PR 4): the timeline to 16 days, marked less certain 10 days out ----------

async function openMap(page: Page, weather: string) {
	await page.route('**/api/tiles/**', (r) => r.abort());
	await page.addInitScript((w) => localStorage.setItem('sw.mapWeather', w), weather);
	await page.goto('/map', { waitUntil: 'networkidle' });
}

async function slideTo(page: Page, v: number) {
	await page.getByRole('slider', { name: 'Time' }).evaluate((el: HTMLInputElement, v) => {
		el.value = String(v);
		el.dispatchEvent(new Event('input', { bubbles: true }));
	}, v);
}

/** Where the "Less certain" mark sits on the radar's slider, in frames. */
async function markAt(page: Page): Promise<number> {
	const slider = page.getByRole('slider', { name: 'Time' });
	const max = Number(await slider.getAttribute('max'));
	const left = await page.getByTitle('Less certain after 10 days').evaluate((el) => el.style.left);
	return (parseFloat(left) / 100) * max;
}

test("the map's loop runs to 16 days, marked less certain 10 days out", async ({
	page,
	isMobile
}) => {
	await openMap(page, 'radar');
	const slider = page.getByRole('slider', { name: 'Time' });
	await expect(slider).toBeVisible({ timeout: 30_000 });
	const pause = page.getByRole('button', { name: 'Pause' });
	if (await pause.count()) await pause.click();
	// A firmer tick, with its words after it where there's room (not on a phone).
	const mark = page.getByTitle('Less certain after 10 days');
	await expect(mark).toHaveText(isMobile ? '' : 'Less certain →');
	const sideways = await page.evaluate(
		() => document.documentElement.scrollWidth - document.documentElement.clientWidth
	);
	expect(sideways).toBeLessThanOrEqual(1);
	// The mark is 10 days out; the last frame 16.
	await slideTo(page, Math.ceil(await markAt(page)));
	await expect(slider).toHaveAttribute('aria-valuetext', /6-hour avg · in 10 days/);
	await slideTo(page, Number(await slider.getAttribute('max')));
	await expect(slider).toHaveAttribute('aria-valuetext', /6-hour avg · in 16 days/);
});

test('days 11–16 are fetched when the slider gets there', async ({ page }) => {
	const asked = new Set<string>();
	page.on('request', (r) => {
		const m = /\/api\/precip\/(f\d+)-[0-9a-f]+\.bin/.exec(r.url());
		if (m) asked.add(m[1]);
	});
	const ix = await (await page.request.get('/api/precip')).json();
	const at: number = ix.less_certain_from;
	// Frames standing for a time past the mark, but the first (the slider blends across it).
	const far: string[] = ix.frames
		.filter((f: { valid: number }) => f.valid > at)
		.sort((a: { valid: number }, b: { valid: number }) => a.valid - b.valid)
		.slice(1)
		.map((f: { t: number }) => `f${f.t}`);
	expect(far.length).toBeGreaterThan(20);
	await openMap(page, 'radar');
	const slider = page.getByRole('slider', { name: 'Time' });
	await expect(slider).toBeVisible({ timeout: 30_000 });
	const pause = page.getByRole('button', { name: 'Pause' });
	if (await pause.count()) await pause.click();
	// Everything to day 10 arrives (the frame just before the mark among it); nothing after.
	await expect.poll(() => asked.size, { timeout: 20_000 }).toBeGreaterThan(40);
	await page.waitForTimeout(2000);
	expect(far.filter((f) => asked.has(f))).toEqual([]);
	await slideTo(page, Number(await slider.getAttribute('max')));
	await expect
		.poll(() => far.filter((f) => asked.has(f)).length, { timeout: 20_000 })
		.toBe(far.length);
});

test('playing stops at the "Less certain" mark', async ({ page }, info) => {
	test.skip(info.project.name !== 'desktop', 'one run is enough');
	await openMap(page, 'radar');
	const slider = page.getByRole('slider', { name: 'Time' });
	await expect(slider).toBeVisible({ timeout: 30_000 });
	const pause = page.getByRole('button', { name: 'Pause' });
	if (await pause.count()) await pause.click();
	const stop = Math.floor(await markAt(page));
	await slideTo(page, stop - 2);
	await page.getByRole('button', { name: 'Play' }).click();
	// Two 6-hour frames to the mark, a rest there, then round to the start.
	const seen: number[] = [];
	for (let i = 0; i < 40 && !(seen.length && seen[seen.length - 1] < stop - 3); i++) {
		await page.waitForTimeout(150);
		seen.push(Number(await slider.inputValue()));
	}
	expect(Math.max(...seen)).toBeLessThanOrEqual(stop + 0.001);
	expect(Math.max(...seen)).toBeGreaterThan(stop - 0.5);
	expect(seen[seen.length - 1]).toBeLessThan(stop - 3);
});

test('the snow total goes on to 14 days and the end', async ({ page }) => {
	await openMap(page, 'totals');
	const slider = page.getByRole('slider', { name: 'Snow total window' });
	await expect(slider).toBeVisible({ timeout: 30_000 });
	const ticks = page.locator('section.controls .ticks span');
	await expect(ticks).toHaveCount(9);
	await expect(ticks.nth(8)).toHaveText('16d');
	// The names never run together (on a narrow slider every other one is left out).
	const boxes = await ticks.evaluateAll((els) =>
		els
			.filter((el) => el.textContent)
			.map((el) => {
				const r = el.getBoundingClientRect();
				return [r.left, r.right];
			})
	);
	for (let i = 1; i < boxes.length; i++)
		expect(boxes[i][0]).toBeGreaterThanOrEqual(boxes[i - 1][1] - 1);
	await slider.focus();
	for (let i = 0; i < 9; i++) await page.keyboard.press('ArrowRight');
	await expect(slider).toHaveAttribute('aria-valuetext', /^Next 16 days, to /);
	await page.keyboard.press('ArrowLeft');
	await expect(slider).toHaveAttribute('aria-valuetext', /^Next 14 days, to /);
	await expect(ticks.nth(7)).toHaveText('14d'); // the mark it's on is named
});
