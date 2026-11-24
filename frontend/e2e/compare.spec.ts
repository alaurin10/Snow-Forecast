// Compare: picking locations by hand, lines on and off, groups kept in the browser and
// moved by link, and the page's layout on a phone (docs/COMPARE-PLAN.md).
import { expect, test, type Page } from '@playwright/test';

/** Page errors, collected while a test runs. */
function watch(page: Page): string[] {
	const problems: string[] = [];
	page.on('pageerror', (e) => problems.push(e.message));
	return problems;
}

const sideways = (page: Page) =>
	page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test('the tabs and the rail put Overview and Map first, then Compare', async ({ page }, info) => {
	await page.goto('/', { waitUntil: 'networkidle' });
	const nav =
		info.project.name === 'phone'
			? page.locator('nav.tabbar')
			: page.getByRole('navigation', { name: 'Main' });
	await expect(nav.getByRole('link')).toHaveText([
		'Overview',
		'Map',
		'Compare',
		'Calendar',
		'Settings'
	]);
	await nav.getByRole('link', { name: 'Compare' }).click();
	await expect(page).toHaveURL(/\/compare/);
	await expect(page.getByRole('heading', { name: 'Compare', level: 1 })).toBeVisible();
});

test('nothing is picked for you; tick some, then Compare', async ({ page }) => {
	const problems = watch(page);
	await page.goto('/compare', { waitUntil: 'networkidle' });
	await expect(page.getByRole('heading', { name: 'Choose locations to compare' })).toBeVisible();
	const items = page.locator('.add .item');
	await expect(items.first()).toBeVisible();
	await expect(page.locator('.add .item[aria-pressed="true"]')).toHaveCount(0);
	const go = page.getByRole('button', { name: /^Compare/ });
	await expect(go).toBeDisabled();
	await items.filter({ hasText: 'Crystal Mountain' }).click();
	await items.filter({ hasText: 'Whistler' }).click();
	await expect(go).toHaveText('Compare 2 locations');
	await go.click();
	await expect(page).toHaveURL(/loc=crystal,whistler/);
	await expect(page.locator('.cr .list li')).toHaveCount(2);
	// Both are lines: two coloured paths on the chart.
	await expect(page.locator('.plot path.line')).toHaveCount(2);
	expect(await sideways(page)).toBeLessThanOrEqual(1);
	expect(problems).toEqual([]);
});

test('lines turn on and off from the rows, at most four at once', async ({ page }) => {
	const problems = watch(page);
	await page.goto('/compare?loc=crystal,snoqualmie,rainy,whistler,revelstoke', {
		waitUntil: 'networkidle'
	});
	const rows = page.locator('.cr .list li');
	await expect(rows).toHaveCount(5);
	await expect(page.locator('.plot path.line')).toHaveCount(4);
	// The fifth joined as a row only; four lines are on, so it can't be drawn yet.
	const revel = page.getByRole('button', { name: /^Revelstoke: line hidden/ });
	await revel.click();
	await expect(page.getByRole('status')).toContainText('Up to 4 lines at once');
	await expect(page.locator('.plot path.line')).toHaveCount(4);
	// Turning one off frees its colour, and the next line takes that colour.
	await page.getByRole('button', { name: /^Snoqualmie Pass: line drawn/ }).click();
	await expect(page).toHaveURL(/on=crystal,,rainy,whistler/);
	await revel.click();
	await expect(page).toHaveURL(/on=crystal,revelstoke,rainy,whistler/);
	await expect(page.locator('.plot path.line')).toHaveCount(4);
	expect(problems).toEqual([]);
});

test('a group is saved in the browser, opens as it was left, and travels by link', async ({
	page,
	browser
}) => {
	const problems = watch(page);
	await page.goto('/compare?loc=rainy,crystal&band=summit&metric=fl&range=10', {
		waitUntil: 'networkidle'
	});
	await page.getByRole('button', { name: 'Save as group' }).click();
	await page.getByLabel('Name').fill('Washington touring');
	await page.getByRole('button', { name: 'Save', exact: true }).click();
	await expect(page.getByRole('status')).toContainText('Saved “Washington touring”');
	await expect(page.locator('.gname')).toHaveText('Washington touring');
	await expect(page.getByRole('button', { name: 'Save as group' })).toHaveCount(0);

	// Changes are kept in the open group: add a location, then come back to the page.
	await page.getByRole('button', { name: 'Add location' }).click();
	await page.locator('.add .item').filter({ hasText: 'Snoqualmie Pass' }).click();
	await page.getByRole('button', { name: 'Done' }).click();
	await expect(page.locator('.cr .list li')).toHaveCount(3);
	await page.goto('/compare', { waitUntil: 'networkidle' });
	await expect(page).toHaveURL(/name=Washington\+touring/);
	await expect(page.locator('.cr .list li')).toHaveCount(3);
	await expect(
		page.getByRole('group', { name: 'Elevation' }).getByRole('button', { name: 'Summit' })
	).toHaveAttribute('aria-pressed', 'true');
	await expect(
		page.getByRole('group', { name: 'Chart metric' }).getByRole('button', { name: /Freezing/ })
	).toHaveAttribute('aria-pressed', 'true');

	// The group menu opens it again after starting a new comparison.
	await page.getByRole('button', { name: /Washington touring/ }).click();
	await page.getByRole('button', { name: 'New comparison' }).click();
	await expect(page.getByRole('heading', { name: 'Choose locations to compare' })).toBeVisible();
	await page.locator('.gpill').click();
	await page.getByRole('button', { name: /^Washington touring/ }).click();
	await expect(page.locator('.cr .list li')).toHaveCount(3);

	// Its link, opened in a browser that has never seen it, offers to save it there.
	const link = page.url();
	const other = await browser.newContext();
	const p2 = await other.newPage();
	await p2.goto(link, { waitUntil: 'networkidle' });
	await expect(p2.locator('.gname')).toHaveText('Washington touring');
	await expect(p2.getByRole('button', { name: 'Save group' })).toBeVisible();
	await expect(p2.locator('.cr .list li')).toHaveCount(3);
	await other.close();
	expect(problems).toEqual([]);
});

test('deleting a group can be undone', async ({ page }) => {
	await page.goto('/compare?loc=crystal', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Save as group' }).click();
	await page.getByLabel('Name').fill('Resorts');
	await page.getByRole('button', { name: 'Save', exact: true }).click();
	await page.locator('.gpill').click();
	await page.getByRole('button', { name: 'Edit groups' }).click();
	await page.getByRole('button', { name: 'Delete Resorts' }).click();
	await page.getByRole('button', { name: 'Close' }).click();
	await expect(page.locator('.gname')).toHaveText('New comparison');
	await page.getByRole('button', { name: 'Undo' }).click();
	await expect(page.locator('.gname')).toHaveText('Resorts');
});

test('Edit removes and reorders; Back undoes a removal', async ({ page }) => {
	await page.goto('/compare?loc=crystal,whistler,rainy', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Edit', exact: true }).click();
	await page.getByRole('button', { name: /^Move Heather–Maple .* up$/ }).click();
	await expect(page).toHaveURL(/loc=crystal,rainy,whistler/);
	await page.getByRole('button', { name: 'Remove Whistler' }).click();
	await expect(page).toHaveURL(/loc=crystal,rainy&/);
	await page.goBack();
	await expect(page).toHaveURL(/loc=crystal,rainy,whistler/);
	await expect(page.locator('.cr .list li')).toHaveCount(3);
});

test('every metric draws on a phone without sideways scrolling', async ({ page }, info) => {
	test.skip(info.project.name !== 'phone', 'the phone layout');
	const problems = watch(page);
	await page.goto('/compare?loc=crystal,snoqualmie,rainy,whistler,revelstoke,sunshine', {
		waitUntil: 'networkidle'
	});
	const metrics = page.getByRole('group', { name: 'Chart metric' });
	for (const m of ['Snow', 'Temp', 'Gusts', 'Cloud', 'Freezing', 'Ratio']) {
		await metrics.getByRole('button', { name: m, exact: true }).click();
		await expect(metrics.getByRole('button', { name: m, exact: true })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		expect(await sideways(page)).toBeLessThanOrEqual(1);
	}
	// The readout keeps its height whether or not every line is drawn.
	const before = (await page.locator('.readout').boundingBox())!.height;
	await page.getByRole('button', { name: /^Crystal Mountain: line drawn/ }).click();
	await expect(page.locator('.plot path.line').first()).toBeAttached();
	expect((await page.locator('.readout').boundingBox())!.height).toBe(before);
	expect(problems).toEqual([]);
});

test('the cards above the chart name every line; the plot has no labels of its own', async ({
	page
}, info) => {
	await page.goto('/compare?loc=rainy,crystal,snoqualmie,whistler&band=summit&metric=temp', {
		waitUntil: 'networkidle'
	});
	const cards = page.locator('.read:not(.spare)');
	await expect(cards).toHaveCount(4);
	for (const name of ['Heather–Maple', 'Crystal Mountain', 'Snoqualmie Pass', 'Whistler'])
		await expect(cards.filter({ hasText: name })).toHaveCount(1);
	await expect(page.locator('.ends, .end')).toHaveCount(0);
	// On phones the cards are two lines (name; value), with the elevation left to the rows.
	const where = cards.first().locator('.where');
	if (info.project.name === 'phone') await expect(where).toHaveCount(0);
	else await expect(where).toHaveText(/Maple Pass · [\d,]+ ft/);
});

test('pointing at a location picks out its line', async ({ page }, info) => {
	test.skip(info.project.name !== 'desktop', 'a mouse pointer');
	await page.goto('/compare?loc=rainy,crystal,whistler&band=summit', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: /^Crystal Mountain: line drawn/ }).hover();
	await expect(page.locator('.plot path.line.hl')).toHaveCount(1);
	await expect(page.locator('.plot path.line.faded')).toHaveCount(2);
	await page.locator('h1').hover();
	await expect(page.locator('.plot path.line.faded')).toHaveCount(0);
});

test('the timeline and the range sit right under the chart, and move it', async ({ page }) => {
	await page.goto('/compare?loc=crystal,whistler&band=summit&metric=temp&range=3', {
		waitUntil: 'networkidle'
	});
	// In the card: the plot, then the timeline, then the range, then the rows.
	const order = await page
		.locator('.chartcard')
		.evaluate((card) =>
			['.plot', '.ct .track', '[aria-label="Time range"]', '.cr'].map((sel) =>
				Math.round(card.querySelector(sel)!.getBoundingClientRect().top)
			)
		);
	expect([...order].sort((a, b) => a - b)).toEqual(order);
	const track = page.getByRole('slider', { name: 'Days the chart shows' });
	const when = page.locator('.readout .when');
	const first = await when.textContent();
	// Tap the sixth day: the window centres on it.
	const box = (await track.boundingBox())!;
	const n = await track.locator('.day').count();
	await page.mouse.click(box.x + (box.width * 5.5) / n, box.y + box.height / 2);
	await expect(when).not.toHaveText(first ?? '');
	await expect(page.getByRole('button', { name: 'One day earlier' })).toBeEnabled();
	// Two drawn lines: two bars a day.
	await expect(track.locator('.day').nth(2).locator('i')).toHaveCount(2);
	// Ten days show every day: nothing to move.
	await page
		.getByRole('group', { name: 'Time range' })
		.getByRole('button', { name: '10 days' })
		.click();
	await expect(page.getByRole('button', { name: 'One day later' })).toBeDisabled();
	await expect(page.locator('.ct .note')).toContainText('Showing all');
});

test('the list under the chart has no day cells: a name, its height and its total', async ({
	page
}) => {
	await page.goto('/compare?loc=crystal,whistler&band=summit', { waitUntil: 'networkidle' });
	await expect(page.locator('.cr .list li')).toHaveCount(2);
	await expect(page.locator('.cellbox, .heat')).toHaveCount(0);
	await expect(page.locator('.cr .list li').first().locator('.sum')).toHaveText(/^\d+\.\d$/);
});

test('tapping a location’s card picks out its line; again clears it; another switches', async ({
	page
}) => {
	await page.goto('/compare?loc=rainy,crystal,whistler&band=summit&metric=temp', {
		waitUntil: 'networkidle'
	});
	const card = (name: string) => page.locator('.read:not(.spare)', { hasText: name });
	const faded = page.locator('.plot path.line.faded');
	const picked = page.locator('.plot path.line.hl');
	await card('Crystal Mountain').click();
	await expect(card('Crystal Mountain')).toHaveAttribute('aria-pressed', 'true');
	await expect(picked).toHaveCount(1);
	await expect(faded).toHaveCount(2);
	// Only one at a time: another card switches to it.
	await card('Whistler').click();
	await expect(card('Whistler')).toHaveAttribute('aria-pressed', 'true');
	await expect(card('Crystal Mountain')).toHaveAttribute('aria-pressed', 'false');
	await expect(picked).toHaveCount(1);
	// The same card again clears it.
	await card('Whistler').click();
	await expect(card('Whistler')).toHaveAttribute('aria-pressed', 'false');
	await page.locator('h1').hover();
	await expect(faded).toHaveCount(0);
});

test('on a desktop, pointing wins while it lasts, then the selection shows again', async ({
	page
}, info) => {
	test.skip(info.project.name !== 'desktop', 'a mouse pointer');
	await page.goto('/compare?loc=rainy,crystal,whistler&band=summit&metric=temp', {
		waitUntil: 'networkidle'
	});
	const card = (name: string) => page.locator('.read:not(.spare)', { hasText: name });
	const lineOf = async () =>
		page.locator('.plot path.line.hl').evaluate((el) => el.getAttribute('class'));
	await card('Crystal Mountain').click();
	const crystal = await lineOf();
	await card('Whistler').hover();
	expect(await lineOf()).not.toBe(crystal);
	await page.locator('h1').hover();
	expect(await lineOf()).toBe(crystal);
	// Turning the selected location's line off clears the selection.
	await page.getByRole('button', { name: /^Crystal Mountain: line drawn/ }).click();
	await page.locator('h1').hover();
	await expect(page.locator('.plot path.line.faded')).toHaveCount(0);
});

test('Share makes an image of the comparison as it is shown', async ({ page }) => {
	await page.goto('/compare?loc=crystal,whistler&band=summit&metric=fl&range=3', {
		waitUntil: 'networkidle'
	});
	await page.getByRole('button', { name: 'Share this comparison' }).click();
	const dialog = page.getByRole('dialog');
	await expect(dialog).toBeVisible();
	const img = dialog.getByRole('img', { name: 'What will be shared' });
	await expect(img).toBeVisible();
	expect(await img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(1000);
	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0);
});

test('the Timeline button hides the timeline, leaving the chart its height', async ({ page }) => {
	await page.goto('/compare?loc=crystal,whistler&band=summit&range=3', {
		waitUntil: 'networkidle'
	});
	const plot = page.locator('.plot');
	const h = (await plot.boundingBox())!.height;
	const toggle = page.getByRole('button', { name: 'Hide the timeline' });
	await toggle.click();
	await expect(page.locator('.ct')).toHaveCount(0);
	expect((await plot.boundingBox())!.height).toBe(h);
	// The forecast chart shares the setting.
	expect(await page.evaluate(() => localStorage.getItem('sw.showTimeline'))).toBe('off');
	await page.getByRole('button', { name: 'Show the timeline' }).click();
	await expect(page.locator('.ct')).toHaveCount(1);
});

test('snow totals follow the setting: from now, or from the first day shown', async ({ page }) => {
	await page.goto('/compare?loc=whistler&band=summit&metric=snow&range=3', {
		waitUntil: 'networkidle'
	});
	// Move the window three days on, then read Whistler's card at the window's end.
	await page.getByRole('button', { name: 'One day later' }).click();
	await page.getByRole('button', { name: 'One day later' }).click();
	await page.getByRole('button', { name: 'One day later' }).click();
	const value = page.locator('.read:not(.spare) .rval').first();
	const fromNow = parseFloat((await value.textContent()) ?? '0');
	await expect(page.locator('.axes')).toContainText('Snow from now');
	await page.goto('/settings');
	await page.getByRole('button', { name: 'From the first day shown' }).click();
	await page.goto('/compare?loc=whistler&band=summit&metric=snow&range=3', {
		waitUntil: 'networkidle'
	});
	for (let i = 0; i < 3; i++) await page.getByRole('button', { name: 'One day later' }).click();
	await expect(page.locator('.axes')).not.toContainText('Snow from now');
	const fromStart = parseFloat((await value.textContent()) ?? '0');
	expect(fromStart).toBeLessThan(fromNow);
	// The row's total for the days shown matches the line's end now.
	await expect(page.locator('.cr .list .sum').first()).toHaveText(fromStart.toFixed(1));
});
