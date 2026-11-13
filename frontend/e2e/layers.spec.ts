// Milestone 4 (docs/APP-NOTES-PLAN.md): the Layers sheet fits a small phone without
// scrolling and its tiles never move when chosen; on desktop it can be pinned open; on
// phones one control at the foot of the map is open at a time; and the forecast chart
// opens full screen on phones.
import { expect, test } from '@playwright/test';

test('Layers fits a small phone without scrolling, and its tiles keep their place', async ({
	browser
}) => {
	const ctx = await browser.newContext({ viewport: { width: 375, height: 667 }, hasTouch: true });
	const page = await ctx.newPage();
	await page.goto('/map', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Layers' }).click();
	const sheet = page.getByRole('dialog', { name: 'Map layers' });
	await expect(sheet).toBeVisible();
	const body = sheet.locator('.body');
	const { sh, ch } = await body.evaluate((b) => ({ sh: b.scrollHeight, ch: b.clientHeight }));
	expect(sh).toBeLessThanOrEqual(ch + 1);
	// "None" comes first in Weather and Terrain.
	for (const group of ['Weather', 'Terrain overlay'])
		await expect(sheet.getByRole('group', { name: group }).getByRole('button').first()).toHaveText(
			'None'
		);

	// Choosing tiles moves nothing.
	const tiles = sheet.getByRole('group', { name: 'Weather' }).getByRole('button');
	const before = await tiles.evaluateAll((els) =>
		els.map((e) => e.getBoundingClientRect()).map((r) => [r.x, r.y, r.width, r.height].join())
	);
	await sheet.getByRole('button', { name: 'Snow total' }).click();
	await sheet.getByRole('button', { name: 'Observed snow' }).click();
	await sheet.getByRole('button', { name: 'Glaciers and cliffs' }).click();
	const after = await tiles.evaluateAll((els) =>
		els.map((e) => e.getBoundingClientRect()).map((r) => [r.x, r.y, r.width, r.height].join())
	);
	expect(after).toEqual(before);
	await expect(sheet.getByRole('button', { name: 'Observed snow' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);

	// A section's (i) says what the chosen option is.
	await sheet.getByRole('button', { name: 'About the weather layers' }).click();
	await expect(sheet).toContainText('Snow that fell, analysed from reports and radar');
	await ctx.close();
});

for (const width of [320, 375]) {
	test(`no Layers label is cut short at ${width} px`, async ({ browser }, info) => {
		test.skip(info.project.name !== 'phone', 'one run is enough');
		const ctx = await browser.newContext({ viewport: { width, height: 700 }, hasTouch: true });
		const page = await ctx.newPage();
		await page.addInitScript(() => localStorage.setItem('sw.mapFeatures', 'ates'));
		await page.goto('/map', { waitUntil: 'networkidle' });
		await page.getByRole('button', { name: 'Layers' }).click();
		const sheet = page.getByRole('dialog', { name: 'Map layers' });
		await expect(sheet).toBeVisible();
		const cut = await sheet.locator('.mp-tiles button > span').evaluateAll((spans) =>
			spans
				.filter((s) => {
					const b = s.parentElement!.getBoundingClientRect();
					const r = s.getBoundingClientRect();
					// Wider than its text box, or spilling out of its tile.
					return (
						s.scrollWidth > s.clientWidth + 1 ||
						r.left < b.left - 0.5 ||
						r.right > b.right + 0.5 ||
						r.top < b.top - 0.5 ||
						r.bottom > b.bottom + 0.5
					);
				})
				.map((s) => s.textContent)
		);
		expect(cut).toEqual([]);
		await ctx.close();
	});
}

test('the dock always has Terrain and Weather, and None turns either off from there', async ({
	page
}) => {
	// A map and many steps: slow on a busy machine.
	test.slow();
	await page.addInitScript(() => {
		localStorage.setItem('sw.mapOverlay', 'none');
		localStorage.setItem('sw.mapWeather', 'radar');
	});
	await page.goto('/map', { waitUntil: 'networkidle' });
	const tabs = page.getByRole('group', { name: 'Map controls' });
	const terrain = tabs.getByRole('button', { name: /^Terrain: / });
	const weather = tabs.getByRole('button', { name: /^Weather: / });
	await expect(terrain).toContainText('Off');
	await expect(weather).toContainText('Radar');
	// Weather: its types, None first; None turns it off and the tab stays.
	const wtypes = page.getByRole('group', { name: 'Weather type' });
	await expect(wtypes.getByRole('button').first()).toHaveText('None');
	await wtypes.getByRole('button', { name: 'No weather layer' }).click();
	await expect(weather).toContainText('Off');
	await expect(page.getByRole('region', { name: 'Precipitation' })).toHaveCount(0);
	await expect(weather).toBeVisible();
	// Terrain: pick a type there; its tab says so.
	await terrain.click();
	const ttypes = page.getByRole('group', { name: 'Terrain type' });
	await ttypes.getByRole('button', { name: 'Elevation bands' }).click();
	await expect(terrain).toContainText('Elevation');
	expect(await page.evaluate(() => localStorage.getItem('sw.mapOverlay'))).toBe('bands');
	// Back on: the weather's controls return under its types.
	await weather.click();
	await wtypes.getByRole('button', { name: 'Snow total' }).click();
	await expect(page.getByRole('region', { name: 'Precipitation' })).toBeVisible();
	// Folded: just the row of tabs.
	await weather.click();
	await expect(wtypes).toHaveCount(0);
	expect((await page.locator('.dock').boundingBox())!.height).toBeLessThan(50);
});

test('phones: one row of tabs at the foot of the map, at most one control open over it', async ({
	page
}, info) => {
	test.skip(info.project.name !== 'phone', 'the dock folds on phones');
	// A map, a reload and many steps: slow on a busy machine.
	test.slow();
	await page.addInitScript(() => {
		localStorage.setItem('sw.mapBase', 'recent');
		localStorage.setItem('sw.mapOverlay', 'sun');
		localStorage.setItem('sw.mapWeather', 'radar');
	});
	await page.goto('/map?loc=rainy', { waitUntil: 'networkidle' });
	const tabs = page.getByRole('group', { name: 'Map controls' });
	await expect(tabs.getByRole('button')).toHaveCount(3);
	// Weather (the last) is open; the others aren't drawn.
	await expect(tabs.getByRole('button', { name: /^Weather: / })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await expect(page.getByRole('region', { name: 'Precipitation' })).toBeVisible();
	await expect(page.getByRole('region', { name: 'Recent satellite' })).toHaveCount(0);
	// Another tab: that one instead.
	await tabs.getByRole('button', { name: /^Satellite: / }).click();
	const sat = page.getByRole('region', { name: 'Recent satellite' });
	await expect(sat).toBeVisible();
	await expect(page.getByRole('region', { name: 'Precipitation' })).toHaveCount(0);
	// The satellite controls are one row, with the long story behind (i).
	await expect(sat.getByRole('button', { name: 'About this view' })).toBeVisible();
	expect((await sat.boundingBox())!.height).toBeLessThan(60);
	// The open tab again: everything folded, just the row of tabs over the map.
	await tabs.getByRole('button', { name: /^Satellite: / }).click();
	await expect(sat).toHaveCount(0);
	await expect(tabs.getByRole('button', { pressed: true })).toHaveCount(0);
	const dock = (await page.locator('.dock').boundingBox())!;
	expect(dock.height).toBeLessThan(50);
});

test('phones: the forecast chart opens truly full screen, with an "All" view, and Escape closes it', async ({
	page
}, info) => {
	test.skip(info.project.name !== 'phone', 'full screen is for phones and tablets');
	// The owner's case: the timeline switched off in the page.
	await page.addInitScript(() => localStorage.setItem('sw.showTimeline', 'off'));
	await page.goto('/location/whistler', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Full screen chart' }).click();
	const full = page.getByRole('dialog', { name: 'Forecast chart, full screen' });
	await expect(full).toBeVisible();
	// The whole window (not trapped in the page's card), and nothing to scroll.
	const vp = page.viewportSize()!;
	const box = (await page.locator('.fsx').boundingBox())!;
	expect(box).toMatchObject({ x: 0, y: 0, width: vp.width, height: vp.height });
	const { sh, ch } = await full.evaluate((e) => ({ sh: e.scrollHeight, ch: e.clientHeight }));
	expect(sh).toBeLessThanOrEqual(ch + 1);
	const plot = full.locator('.plot');
	expect(await plot.evaluate((e) => getComputedStyle(e).touchAction)).toBe('none');
	expect((await plot.boundingBox())!.height).toBeGreaterThan(250);
	await expect(full.getByRole('group', { name: 'Chart metric' })).toBeVisible();
	await expect(full.getByRole('slider', { name: 'Days the chart shows' })).toBeVisible();
	// Clear of the edges: room at the top, the controls at the foot above the corners.
	const bar = (await page.locator('.fsbar').boundingBox())!;
	expect(bar.y).toBeGreaterThanOrEqual(14);
	const range = page.locator('.fsfoot').getByRole('group', { name: 'Time range' });
	const rb = (await range.boundingBox())!;
	expect(vp.height - (rb.y + rb.height)).toBeGreaterThanOrEqual(20);
	expect(rb.height).toBeGreaterThanOrEqual(40);
	// The lower panel: cloud cover and the chance of precipitation.
	await expect(full.locator('.lowcap')).toContainText('Chance of precipitation');
	await expect(full.locator('.lplot')).toBeVisible();

	// All: every measure, six lanes on one time axis; reading one reads them all.
	await page.getByRole('button', { name: 'All', exact: true }).click();
	const lanes = full.locator('.fc.lane:not(.tlonly)');
	await expect(lanes).toHaveCount(6);
	await expect(full.locator('.lanehead:visible')).toHaveCount(6);
	for (const name of ['Cloud cover', 'Snow ratio'])
		await expect(full.locator('.lanehead:visible', { hasText: name })).toHaveCount(1);
	const time = full.locator('.ltime:visible');
	const before = await time.textContent();
	const wind = (await lanes.nth(2).locator('.plot').boundingBox())!;
	await page.mouse.move(wind.x + wind.width * 0.85, wind.y + wind.height / 2);
	await expect(time).not.toHaveText(before ?? '');
	expect(await full.evaluate((e) => e.scrollHeight <= e.clientHeight + 1)).toBe(true);

	await page.keyboard.press('Escape');
	await expect(full).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Full screen chart' })).toBeFocused();
});

test('phones: the map buttons sit bottom right on the dock, with the rarer ones under More', async ({
	page
}, info) => {
	test.skip(info.project.name !== 'phone', 'the buttons move on phones and tablets');
	await page.goto('/map', { waitUntil: 'networkidle' });
	const vp = page.viewportSize()!;
	const layers = (await page.getByRole('button', { name: 'Layers' }).boundingBox())!;
	const tabs = (await page.getByRole('group', { name: 'Map controls' }).boundingBox())!;
	expect(layers.x + layers.width).toBeGreaterThan(vp.width - 20);
	expect(layers.y + layers.height).toBeLessThan(tabs.y);
	expect(layers.y).toBeGreaterThan(vp.height / 2);
	// No zoom buttons (pinch, double tap); the compass stays.
	await expect(page.getByRole('button', { name: 'Zoom in' })).toBeHidden();
	await expect(page.locator('.maplibregl-ctrl-compass')).toBeVisible();
	// The rarer tools behind More; a tap on the map closes it.
	await expect(page.getByRole('button', { name: 'Offline maps' })).toHaveCount(0);
	await page.getByRole('button', { name: 'More map tools' }).click();
	const menu = page.getByRole('group', { name: 'More map tools' });
	for (const name of ['Measure', 'Offline maps', 'About this map'])
		await expect(menu.getByRole('button', { name })).toBeVisible();
	await page.mouse.click(60, 200);
	await expect(menu).toHaveCount(0);
	// Folded, then the weather's controls opened: the buttons rise with them.
	const weather = page.getByRole('button', { name: /^Weather: / });
	if ((await weather.getAttribute('aria-pressed')) === 'true') await weather.click();
	await expect(weather).toHaveAttribute('aria-pressed', 'false');
	await page.waitForTimeout(400);
	const folded = (await page.getByRole('button', { name: 'Layers' }).boundingBox())!.y;
	await weather.click();
	await expect
		.poll(async () => (await page.getByRole('button', { name: 'Layers' }).boundingBox())!.y)
		.toBeLessThan(folded - 30);
});
