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

test('phones: the forecast chart opens full screen, and Escape closes it', async ({
	page
}, info) => {
	test.skip(info.project.name !== 'phone', 'full screen is for phones and tablets');
	await page.goto('/location/whistler', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Full screen chart' }).click();
	const full = page.getByRole('dialog', { name: 'Forecast chart, full screen' });
	await expect(full).toBeVisible();
	const plot = full.locator('.plot');
	expect(await plot.evaluate((e) => getComputedStyle(e).touchAction)).toBe('none');
	expect((await plot.boundingBox())!.height).toBeGreaterThan(200);
	await expect(full.getByRole('group', { name: 'Chart metric' })).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(full).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Full screen chart' })).toBeFocused();
});
