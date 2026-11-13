// The map's newer layers and tools: snow stations, field reports and ATES ratings are
// offered in the Layers sheet and remembered; Measure opens its panel, and a GPX track
// opens in it without being uploaded.
import { expect, test } from '@playwright/test';

test('stations, field reports and ATES are offered and remembered', async ({ page }) => {
	for (const path of [
		'/api/map/stations',
		'/api/avalanche/observations.geojson',
		'/api/overlays/ates.geojson'
	])
		expect((await page.request.get(path)).status(), path).toBe(200);
	await page.goto('/map', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Layers' }).click();
	const sheet = page.getByRole('dialog', { name: 'Map layers' });
	for (const name of ['Snow stations', 'Field reports', 'ATES terrain ratings']) {
		const tile = sheet.getByRole('button', { name });
		await expect(tile).toHaveAttribute('aria-pressed', 'false');
		await tile.click();
		await expect(tile).toHaveAttribute('aria-pressed', 'true');
	}
	await expect(sheet.getByRole('button', { name: 'Huts, trailheads, passes' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await sheet.getByRole('button', { name: 'Close' }).click();
	await page.reload({ waitUntil: 'networkidle' });
	const features = await page.evaluate(() => localStorage.getItem('sw.mapFeatures'));
	for (const f of ['stations', 'obs', 'ates', 'places', 'glaciers'])
		expect(features?.split(',')).toContain(f);
});

test('measure opens its panel, and a GPX track opens in it', async ({ page }) => {
	const uploads: string[] = [];
	page.on('request', (r) => r.method() !== 'GET' && uploads.push(r.url()));
	await page.goto('/map', { waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Measure' }).click();
	const panel = page.getByRole('region', { name: 'Measure' });
	await expect(panel).toContainText('Tap the map to add points');
	const chooser = page.waitForEvent('filechooser');
	await panel.getByRole('button', { name: 'Open GPX…' }).click();
	await (
		await chooser
	).setFiles({
		name: 'tour.gpx',
		mimeType: 'application/gpx+xml',
		buffer: Buffer.from(
			'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">' +
				'<trk><name>Snow Lake tour</name><trkseg>' +
				'<trkpt lat="47.445" lon="-121.424"/><trkpt lat="47.452" lon="-121.43"/>' +
				'<trkpt lat="47.46" lon="-121.44"/></trkseg></trk></gpx>'
		)
	});
	await expect(panel).toContainText('Snow Lake tour');
	await expect(panel).toContainText('GPX · read on this device');
	await panel.getByRole('button', { name: 'Done' }).click();
	await expect(panel).toBeHidden();
	expect(uploads).toEqual([]);
});
