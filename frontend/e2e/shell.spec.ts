// The shell doesn't move: the desktop rail is in one place on every page and never
// grows, controls keep their size when selected, notices don't push the page down, and
// a location's Map button opens the map on it.
import { expect, test, type Locator, type Page } from '@playwright/test';

const rect = async (l: Locator) => {
	const b = (await l.boundingBox())!;
	return [b.x, b.y, b.width, b.height].map(Math.round);
};
/** Every tab's box, in order. */
const tabRects = (page: Page) =>
	page
		.getByRole('tablist', { name: 'Sections' })
		.getByRole('tab')
		.evaluateAll((els) =>
			els.map((e) => {
				const b = e.getBoundingClientRect();
				return [b.x, b.y, b.width, b.height].map(Math.round);
			})
		);

test('the desktop rail is in the same place on every page', async ({ page }, info) => {
	test.skip(info.project.name !== 'desktop', 'the rail is desktop only');
	const rail = page.getByRole('complementary', { name: 'Navigation' });
	const boxes: number[][] = [];
	for (const path of ['/', '/calendar', '/map', '/location/whistler', '/settings']) {
		await page.goto(path, { waitUntil: 'networkidle' });
		await expect(page.locator('main')).not.toContainText('Loading…', { timeout: 10_000 });
		boxes.push(await rect(rail));
	}
	for (const b of boxes) expect(b).toEqual(boxes[0]);
	expect(boxes[0].slice(0, 3)).toEqual([14, 14, 248]);
});

test('sections are the page’s tabs on desktop, by click or 1–4', async ({ page }, info) => {
	test.skip(info.project.name !== 'desktop', 'the rail is desktop only');
	await page.goto('/location/whistler', { waitUntil: 'networkidle' });
	const list = page.locator('.locs');
	const before = await rect(list);
	const tabs = page.getByRole('tablist', { name: 'Sections' });
	await expect(tabs).toBeVisible();
	// The rail lists locations only: opening one doesn't push the others down.
	await expect(page.locator('#rail').getByRole('tab')).toHaveCount(0);
	const rects = await tabRects(page);
	await page.keyboard.press('2');
	await expect(tabs.getByRole('tab', { selected: true })).toHaveText('Models');
	await page.keyboard.press('4');
	await expect(tabs.getByRole('tab', { selected: true })).toHaveText('Observed');
	await tabs.getByRole('tab', { name: 'Forecast' }).click();
	await expect(tabs.getByRole('tab', { selected: true })).toHaveText('Forecast');
	expect(await tabRects(page)).toEqual(rects);
	expect(await rect(list)).toEqual(before);
});

test('desktop: once the controls scroll away, a compact pill keeps the elevation', async ({
	page
}, info) => {
	test.skip(info.project.name !== 'desktop', 'phones have their own sticky row');
	await page.goto('/location/whistler', { waitUntil: 'networkidle' });
	const tabs = page.getByRole('tablist', { name: 'Sections' });
	const head = page.getByRole('group', { name: 'Elevation', exact: true });
	const compact = page.getByRole('group', { name: /^Elevation, / });
	// Under the name, above the outlook: nothing between the outlook and the section.
	const outlook = page.getByRole('region', { name: 'Outlook' });
	expect((await tabs.boundingBox())!.y).toBeLessThan((await outlook.boundingBox())!.y);
	// At the top the compact pill is hidden (and out of the accessibility tree).
	await expect(compact).toHaveCount(0);

	// Scrolled down: the tabs go with the page; the compact picker shows at the top right.
	await page.mouse.wheel(0, 1200);
	await expect(compact).toBeVisible();
	expect((await tabs.boundingBox())!.y).toBeLessThan(0);
	const pill = (await compact.boundingBox())!;
	expect(pill.y).toBeLessThan(30);
	expect(pill.height).toBeLessThan(44);
	// Only the pill: no name pill or band beside it.
	await expect(page.locator('.bandwrap')).not.toContainText(/[A-Za-z]{3}/);
	// Numbers only, and in step with the header's picker.
	await expect(compact.getByRole('button').first()).toHaveText(/^[\d,]+$/);
	await compact.getByRole('button').last().click();
	await expect(head.getByRole('button').last()).toHaveAttribute('aria-pressed', 'true');

	// Switching section from down here goes back up to the tabs.
	await page.keyboard.press('2');
	await expect(tabs.getByRole('tab', { selected: true })).toHaveText('Models');
	await expect.poll(async () => (await tabs.boundingBox())!.y).toBeGreaterThanOrEqual(0);
	await expect(compact).toHaveCount(0);
});

test('wide windows: the compact elevation stands stacked beside the page', async ({
	page
}, info) => {
	test.skip(info.project.name !== 'desktop', 'wide windows are desktops');
	await page.setViewportSize({ width: 1920, height: 1000 });
	await page.goto('/location/whistler', { waitUntil: 'networkidle' });
	await page.mouse.wheel(0, 1200);
	const compact = page.getByRole('group', { name: /^Elevation, / });
	await expect(compact).toBeVisible();
	const pill = (await compact.boundingBox())!;
	const main = (await page.locator('main').boundingBox())!;
	// In the margin right of the page, not over it; one above another.
	expect(pill.x).toBeGreaterThanOrEqual(main.x + main.width);
	expect(pill.x + pill.width).toBeLessThanOrEqual(1920);
	expect(pill.height).toBeGreaterThan(pill.width);
});

test('phones: only the elevation sticks, as a compact pill', async ({ page }, info) => {
	test.skip(info.project.name !== 'phone', 'the phone layout');
	await page.goto('/location/whistler', { waitUntil: 'networkidle' });
	const row = page.locator('.mrow');
	const compact = page.locator('.bandwrap').getByRole('group');
	await expect(compact).toHaveCount(0);
	await page.evaluate(() => window.scrollTo(0, 900));
	await expect(compact).toBeVisible();
	// The conditions row scrolls away with the page; the pill stays at the top.
	expect((await row.boundingBox())!.y).toBeLessThan(0);
	expect((await compact.boundingBox())!.y).toBeLessThan(60);
	await compact.getByRole('button').last().click();
	await expect(row.getByRole('group').getByRole('button').last()).toHaveAttribute(
		'aria-pressed',
		'true'
	);
});

test('desktop chart: the range and timeline switch sit under the plot', async ({ page }, info) => {
	test.skip(info.project.name !== 'desktop', 'phones already have them at the foot');
	await page.goto('/location/whistler', { waitUntil: 'networkidle' });
	const range = page.getByRole('group', { name: 'Time range' });
	const cards = page.getByRole('group', { name: 'Chart metric' });
	const title = page.getByRole('heading', { name: 'Forecast', exact: true });
	expect((await title.boundingBox())!.y).toBeLessThan((await cards.boundingBox())!.y);
	expect((await range.boundingBox())!.y).toBeGreaterThan((await cards.boundingBox())!.y + 200);
	const slider = page.getByRole('slider', { name: 'Days the chart shows' });
	if (await slider.count())
		expect((await range.boundingBox())!.y).toBeGreaterThan((await slider.boundingBox())!.y);
});

test('choosing a tab or an elevation moves nothing', async ({ page }) => {
	await page.goto('/location/whistler', { waitUntil: 'networkidle' });
	const rects = await tabRects(page);
	await page.getByRole('tab', { name: 'Observed' }).click();
	expect(await tabRects(page)).toEqual(rects);
	const elev = page.getByRole('group', { name: /^Elevation/ }).getByRole('button');
	const boxes = () =>
		elev.evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().width)));
	const widths = await boxes();
	await elev.first().click();
	await expect(elev.first()).toHaveAttribute('aria-pressed', 'true');
	expect(await boxes()).toEqual(widths);
});

test('a location’s Map button opens the map on it', async ({ page }) => {
	await page.goto('/location/whistler', { waitUntil: 'networkidle' });
	await page.getByRole('link', { name: 'View Whistler on the map' }).click();
	await expect(page).toHaveURL(/\/map\?loc=whistler$/);
	const popup = page.locator('.maplibregl-popup');
	await expect(popup).toContainText('Whistler');
	await expect(popup.getByRole('link', { name: 'Open forecast →' })).toBeVisible();
	await expect(page.getByRole('button', { name: '3D terrain' })).toHaveAttribute(
		'aria-pressed',
		'false'
	);
});

test('a notice floats over the page and can be closed', async ({ page, context }) => {
	await page.goto('/location/whistler', { waitUntil: 'networkidle' });
	const title = page.getByRole('heading', { level: 1 });
	const before = await rect(title);
	await context.setOffline(true);
	const notice = page.getByRole('status').filter({ hasText: 'Offline' });
	await expect(notice).toBeVisible();
	expect(await rect(title)).toEqual(before);
	await notice.getByRole('button', { name: 'Close notice' }).click();
	await expect(notice).toHaveCount(0);
	await context.setOffline(false);
});

test('the phone conditions pill is an icon, the same width whatever it shows', async ({
	page
}, info) => {
	test.skip(info.project.name !== 'phone', 'the icon pill is the phone layout');
	for (const width of [320, 375]) {
		await page.setViewportSize({ width, height: 740 });
		await page.goto('/location/whistler', { waitUntil: 'networkidle' });
		const pill = page.getByRole('button', { name: /· updated / });
		await expect(pill.locator('svg.wx')).toBeVisible();
		// The words are its accessible name, not its text: nothing to cut off.
		expect(await pill.evaluate((e) => e.scrollWidth <= e.clientWidth)).toBe(true);
		const before = (await pill.boundingBox())!.width;
		await page
			.getByRole('group', { name: /^Elevation/ })
			.getByRole('button')
			.first()
			.click();
		expect((await pill.boundingBox())!.width).toBe(before);
		// A tap shows the words; Escape puts them away.
		await pill.click();
		await expect(page.getByRole('status').filter({ hasText: /· updated / })).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(page.locator('#wxpop')).toHaveCount(0);
	}
});
