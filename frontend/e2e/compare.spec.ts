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
	await expect(page.locator('.plot path.line, .plot rect.cloud').first()).toBeAttached();
	expect((await page.locator('.readout').boundingBox())!.height).toBe(before);
	expect(problems).toEqual([]);
});

test('lines are named at their ends, except where they end on top of each other', async ({
	page
}) => {
	const url = '/compare?loc=rainy,crystal,snoqualmie,whistler&band=summit';
	const labels = page.locator('.ends .end');
	// Temperature over 10 days: four line ends well apart, four labels.
	await page.goto(`${url}&metric=temp&range=10`, { waitUntil: 'networkidle' });
	await expect(labels).toHaveCount(4);
	for (const name of ['Snoqualmie', 'Crystal', 'Heather–M', 'Whistler'])
		await expect(labels.filter({ hasText: name })).toHaveCount(1);
	const boxes = await labels.evaluateAll((els) =>
		els.map((el) => el.getBoundingClientRect()).map((r) => [r.top, r.bottom])
	);
	boxes.sort((a, b) => a[0] - b[0]);
	for (let i = 1; i < boxes.length; i++)
		expect(boxes[i][0]).toBeGreaterThanOrEqual(boxes[i - 1][1] - 1);
	// Snow: Crystal and Snoqualmie both end near nothing, on top of each other, so only
	// the other two are labelled; the readout cards name all four.
	await page.goto(`${url}&metric=snow&range=5`, { waitUntil: 'networkidle' });
	await expect(labels).toHaveCount(2);
	await expect(labels.filter({ hasText: 'Whistler' })).toHaveCount(1);
	await expect(labels.filter({ hasText: 'Crystal' })).toHaveCount(0);
	await expect(page.locator('.read:not(.spare)')).toHaveCount(4);
	// Gusts: all four end bunched together, so none is labelled.
	await page.goto(`${url}&metric=wind&range=5`, { waitUntil: 'networkidle' });
	await expect(labels).toHaveCount(0);
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
