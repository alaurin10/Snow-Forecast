// Map taps open one panel in one place (docs/APP-NOTES-PLAN.md, milestone 3): a snow
// station, a glacier and bare ground each open the map panel at the same spot on screen,
// on the most specific thing under the tap, with chips for the rest, ranked for the zoom;
// the map itself doesn't move. The fixtures (e2e/serve.sh) put a station 0.02° east of
// Rainy Pass and a glacier just south of it.
import { expect, test, type Page } from '@playwright/test';

/** Pixels per degree of longitude at the zoom a location opens at (11.5, 512 px tiles). */
const PX_LON = (512 * 2 ** 11.5) / 360;
/** Pixels per degree of latitude there (Mercator, at 48.51° N). */
const PX_LAT = PX_LON / Math.cos((48.511 * Math.PI) / 180);

/** Rainy Pass's pin on screen, once the map has stopped moving. */
async function pin(page: Page) {
	const el = page.getByRole('button', { name: /^Heather–Maple \/ Rainy Pass:/ });
	let last: { x: number; y: number } | null = null;
	for (let i = 0; i < 60; i++) {
		const b = await el.boundingBox();
		const c = b && { x: b.x + b.width / 2, y: b.y + b.height / 2 };
		if (c && last && Math.abs(c.x - last.x) < 0.5 && Math.abs(c.y - last.y) < 0.5) return c;
		last = c;
		await page.waitForTimeout(120);
	}
	throw new Error('the map kept moving');
}

async function panelBox(page: Page) {
	const panel = page.locator('[data-map-panel]');
	// The phone sheet eases to its height.
	await page.waitForTimeout(400);
	const b = (await panel.boundingBox())!;
	return { x: Math.round(b.x), y: Math.round(b.y), width: Math.round(b.width), h: b.height };
}

test('a station, a glacier and bare ground open the same panel in the same place', async ({
	page
}, info) => {
	await page.addInitScript(() => localStorage.setItem('sw.mapFeatures', 'stations,glaciers'));
	await page.goto('/map?loc=rainy', { waitUntil: 'networkidle' });
	const desktop = info.project.name === 'desktop';

	// The location's popup is open: the first tap only closes it.
	let p = await pin(page);
	await page.mouse.click(p.x - 0.02 * PX_LON, p.y);

	// A station: its own panel, with nothing else here but the spot.
	p = await pin(page);
	await expect(async () => {
		await page.mouse.click(p.x + 0.02 * PX_LON, p.y);
		await expect(page.getByRole('dialog', { name: 'Rainy Pass test station' })).toBeVisible({
			timeout: 1000
		});
	}).toPass({ timeout: 15_000 });
	// The map stays where it was.
	expect(await pin(page)).toEqual(p);
	const station = page.getByRole('dialog', { name: 'Rainy Pass test station' });
	await expect(station).toContainText('Snow station');
	await expect(station).toContainText('Snow depth');
	const first = await panelBox(page);
	if (desktop) {
		// Docked to the right edge.
		const vp = page.viewportSize()!;
		expect(first.x + first.width).toBeGreaterThan(vp.width - 20);
		expect(first.y).toBeLessThan(20);
	}

	// With the panel open, a tap elsewhere on the map only puts it away.
	p = await pin(page);
	await page.mouse.click(p.x, p.y + 0.014 * PX_LAT);
	await expect(page.locator('[data-map-panel]')).toHaveCount(0);

	// A glacier: the spot first, named for the glacier, with the glacier's own card a chip
	// (or a tap on its line) away.
	await page.mouse.click(p.x, p.y + 0.014 * PX_LAT);
	const onIce = page.getByRole('dialog', { name: 'This spot · Test Glacier' });
	await expect(onIce).toBeVisible();
	await expect(onIce.getByRole('button', { name: 'This spot', pressed: true })).toBeVisible();
	await expect(
		onIce.getByRole('button', { name: 'Glacier', exact: true, pressed: false })
	).toBeVisible();
	expect(await panelBox(page)).toMatchObject(
		desktop ? { x: first.x, y: first.y, width: first.width } : first
	);
	// 0.02° × 0.008° at 48.5° N: about 1.5 km × 0.9 km.
	const line = onIce.getByRole('button', { name: /Test Glacier/ });
	await expect(line).toContainText(/1\.3 km²|1\.2 km²|3\d\d acres/);
	await line.click();
	const glacier = page.getByRole('dialog', { name: 'Test Glacier', exact: true });
	await expect(glacier).toBeVisible();
	await expect(
		glacier.getByRole('button', { name: 'Glacier', exact: true, pressed: true })
	).toBeVisible();
	await expect(glacier).toContainText(/1\.3 km²|1\.2 km²|3\d\d acres/);
	expect(await panelBox(page)).toMatchObject(
		desktop ? { x: first.x, y: first.y, width: first.width } : first
	);

	// Bare ground (after a tap to put the panel away): the spot, in the same place.
	p = await pin(page);
	await page.mouse.click(p.x - 0.02 * PX_LON, p.y);
	await expect(page.locator('[data-map-panel]')).toHaveCount(0);
	await page.mouse.click(p.x - 0.02 * PX_LON, p.y);
	const spot = page.getByRole('dialog', { name: 'This spot', exact: true });
	await expect(spot).toBeVisible();
	await expect(spot.getByRole('region', { name: 'Terrain' })).toBeVisible();
	await expect(spot.getByRole('region', { name: 'Snow and weather' })).toBeVisible();
	await expect(spot.getByText('About these numbers')).toBeVisible();
	expect(await panelBox(page)).toMatchObject(
		desktop ? { x: first.x, y: first.y, width: first.width } : first
	);

	await page.keyboard.press('Escape');
	await expect(page.locator('[data-map-panel]')).toHaveCount(0);

	// Zoomed out too: the spot first, the glacier a chip after it.
	await page.getByRole('button', { name: 'Zoom out' }).click();
	await page.getByRole('button', { name: 'Zoom out' }).click();
	p = await pin(page);
	await page.mouse.click(p.x, p.y + (0.0165 * PX_LAT) / 4);
	await expect(page.getByRole('dialog', { name: 'This spot · Test Glacier' })).toBeVisible();
	await expect(
		page.getByRole('button', { name: 'Glacier', exact: true, pressed: false })
	).toBeVisible();
});

test('phones: the sheet grows and shrinks from its title bar or a swipe anywhere on it', async ({
	page
}, info) => {
	test.skip(info.project.name !== 'phone', 'the sheet is for phones and tablets');
	await page.goto('/map?loc=rainy', { waitUntil: 'networkidle' });
	let p = await pin(page);
	await page.mouse.click(p.x - 0.02 * PX_LON, p.y);
	p = await pin(page);
	await expect(async () => {
		await page.mouse.click(p.x - 0.02 * PX_LON, p.y);
		await expect(page.getByRole('dialog', { name: 'This spot' })).toBeVisible({ timeout: 1000 });
	}).toPass({ timeout: 15_000 });
	const sheet = page.locator('[data-map-panel]');
	const peek = (await panelBox(page)).h;
	// A tap on the title (not just the little handle).
	await sheet.getByText('This spot', { exact: true }).first().click();
	await expect.poll(async () => (await panelBox(page)).h).toBeGreaterThan(peek * 1.5);
	await expect(page.getByRole('button', { name: 'Make the panel smaller' })).toBeVisible();
	// Dragging the title down puts it back to the peek; the map underneath stays put.
	const before = await pin(page);
	const t = (await sheet.locator('.kind').boundingBox())!;
	await page.mouse.move(t.x + 40, t.y + 5);
	await page.mouse.down();
	for (let i = 1; i <= 10; i++) await page.mouse.move(t.x + 40, t.y + 5 + i * 25);
	await page.mouse.up();
	await expect.poll(async () => Math.round((await panelBox(page)).h)).toBe(Math.round(peek));
	expect(await pin(page)).toEqual(before);

	// A finger anywhere on it: swiping up the content at the peek grows the sheet (rather
	// than scrolling), and pulling down from the top of its content shrinks it again.
	const cdp = await page.context().newCDPSession(page);
	const swipe = async (x: number, from: number, to: number) => {
		await cdp.send('Input.dispatchTouchEvent', {
			type: 'touchStart',
			touchPoints: [{ x, y: from }]
		});
		for (let i = 1; i <= 8; i++)
			await cdp.send('Input.dispatchTouchEvent', {
				type: 'touchMove',
				touchPoints: [{ x, y: from + ((to - from) * i) / 8 }]
			});
		await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
	};
	const terrain = (await sheet.getByRole('region', { name: 'Terrain' }).boundingBox())!;
	await swipe(terrain.x + 60, terrain.y + 30, terrain.y - 120);
	await expect.poll(async () => (await panelBox(page)).h).toBeGreaterThan(peek * 1.5);
	expect(await pin(page)).toEqual(before);
	const grown = (await sheet.getByRole('region', { name: 'Terrain' }).boundingBox())!;
	await swipe(grown.x + 60, grown.y + 20, grown.y + 200);
	await expect.poll(async () => Math.round((await panelBox(page)).h)).toBe(Math.round(peek));
	expect(await pin(page)).toEqual(before);
});

test('touch: a tap opens the panel, a double tap (or double tap and drag) only zooms', async ({
	page
}, info) => {
	test.skip(info.project.name !== 'phone', 'touch');
	await page.goto('/map?loc=rainy', { waitUntil: 'networkidle' });
	const cdp = await page.context().newCDPSession(page);
	const touch = (type: string, x?: number, y?: number) =>
		cdp.send('Input.dispatchTouchEvent', {
			type,
			touchPoints: x == null ? [] : [{ x, y: y! }]
		});
	const tap = async (x: number, y: number) => {
		await touch('touchStart', x, y);
		await touch('touchEnd');
	};
	const panel = page.locator('[data-map-panel]');
	// A first tap closes the location's popup, or opens the panel (put away with Escape).
	let p = await pin(page);
	const at = { x: Math.round(p.x - 0.02 * PX_LON), y: Math.round(p.y) };
	await tap(at.x, at.y);
	await page.waitForTimeout(1200);
	await page.keyboard.press('Escape');
	await expect(panel).toHaveCount(0);

	// A gesture's touches, sent together so they arrive as quickly as a finger's (one at a
	// time, each waits for the page, which is busy drawing after a zoom).
	const gesture = (steps: [string, number?, number?][]) =>
		Promise.all(steps.map(([type, x, y]) => touch(type, x, y)));

	// A double tap zooms in, and opens nothing.
	await gesture([
		['touchStart', at.x, at.y],
		['touchEnd'],
		['touchStart', at.x, at.y],
		['touchEnd']
	]);
	await page.waitForTimeout(800);
	await expect(panel).toHaveCount(0);

	// A double tap held and dragged (one-finger zoom): nothing either.
	await pin(page);
	await gesture([
		['touchStart', at.x, at.y],
		['touchEnd'],
		['touchStart', at.x, at.y],
		...[1, 2, 3, 4, 5, 6].map((i): [string, number, number] => ['touchMove', at.x, at.y + i * 15]),
		['touchEnd']
	]);
	await page.waitForTimeout(800);
	await expect(panel).toHaveCount(0);

	// The first tap after that zoom opens the panel; the first tap after it closes it.
	p = await pin(page);
	await page.waitForTimeout(600);
	await tap(Math.round(p.x - 60), Math.round(p.y));
	await expect(panel).toBeVisible();
	await page.waitForTimeout(600);
	await tap(Math.round(p.x - 60), Math.round(p.y));
	await expect(panel).toHaveCount(0);
});

test('touch: the first tap after a pan or a pinch opens the panel', async ({ page }, info) => {
	test.skip(info.project.name !== 'phone', 'touch');
	await page.goto('/map?loc=rainy', { waitUntil: 'networkidle' });
	const cdp = await page.context().newCDPSession(page);
	const touch = (type: string, points: { x: number; y: number }[] = []) =>
		cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points });
	const tap = async (x: number, y: number) => {
		await touch('touchStart', [{ x, y }]);
		await touch('touchEnd');
	};
	const panel = page.locator('[data-map-panel]');
	// Open ground left of Rainy Pass (clear of its popup).
	const p = await pin(page);
	const [cx, cy] = [Math.round(p.x - 0.02 * PX_LON), Math.round(p.y + 40)];
	// Put away the location's popup (or a panel) first.
	await tap(cx, cy);
	await page.waitForTimeout(800);
	await page.keyboard.press('Escape');
	await expect(panel).toHaveCount(0);

	// A pan, then one tap: the panel. One more tap puts it away.
	await touch('touchStart', [{ x: cx, y: cy }]);
	for (let i = 1; i <= 6; i++) await touch('touchMove', [{ x: cx + i * 12, y: cy + i * 8 }]);
	await touch('touchEnd');
	await page.waitForTimeout(700);
	await tap(cx, cy);
	await expect(panel).toBeVisible();
	await page.waitForTimeout(700);
	await tap(cx, cy);
	await expect(panel).toHaveCount(0);

	// A pinch, then one tap: the panel.
	await touch('touchStart', [
		{ x: cx - 40, y: cy },
		{ x: cx + 40, y: cy }
	]);
	for (let i = 1; i <= 6; i++)
		await touch('touchMove', [
			{ x: cx - 40 - i * 10, y: cy },
			{ x: cx + 40 + i * 10, y: cy }
		]);
	await touch('touchEnd');
	await page.waitForTimeout(900);
	await tap(cx, cy);
	await expect(panel).toBeVisible();
});

test('phones: the tab bar is icons only on the map, at the same height', async ({ page }, info) => {
	test.skip(info.project.name !== 'phone', 'the tab bar is for phones and tablets');
	const bar = page.getByRole('navigation', { name: 'Main' });
	await page.goto('/', { waitUntil: 'networkidle' });
	const wide = (await bar.boundingBox())!;
	await expect(bar.getByText('Overview')).toBeVisible();
	await page.goto('/map', { waitUntil: 'networkidle' });
	await expect(bar).toHaveClass(/compact/);
	await expect(bar.getByText('Overview')).toBeHidden();
	await expect.poll(async () => (await bar.boundingBox())!.width).toBeLessThan(wide.width - 100);
	expect(Math.round((await bar.boundingBox())!.height)).toBe(Math.round(wide.height));
});
