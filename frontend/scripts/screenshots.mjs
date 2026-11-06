// Screenshot the app at phone, tablet and desktop widths in light and dark,
// and fail if any page scrolls sideways.
//
//   node scripts/screenshots.mjs [baseUrl] [outDir] [resortId] [tourId]
//
// Needs the API serving the built frontend, e.g. from backend/:
//   uv run snowwatch init && uv run snowwatch rebuild --from tests/fixtures/live-20261104
//   uv run uvicorn snowwatch.api.app:app --port 8000
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const base = process.argv[2] ?? 'http://localhost:8000';
const out = process.argv[3] ?? 'screenshots';
const loc = process.argv[4] ?? 'whistler';
const tour = process.argv[5] ?? 'rainy';
mkdirSync(out, { recursive: true });

const widths = [380, 768, 1280];
const themes = ['light', 'dark'];
const pages = [
	{ name: 'overview', path: '/' },
	{ name: 'calendar', path: '/calendar' },
	{ name: 'more', path: '/more' },
	{ name: `${loc}-forecast`, path: `/location/${loc}` },
	{ name: `${loc}-models`, path: `/location/${loc}`, tab: 'Models' },
	{ name: `${loc}-backcountry`, path: `/location/${loc}`, tab: 'Backcountry' },
	{ name: `${tour}-forecast`, path: `/location/${tour}` },
	{ name: `${tour}-backcountry`, path: `/location/${tour}`, tab: 'Backcountry' },
	{ name: `${loc}-observed`, path: `/location/${loc}`, tab: 'Observed' },
	{ name: 'crystal-forecast', path: '/location/crystal' },
	{ name: 'crystal-observed', path: '/location/crystal', tab: 'Observed' },
	{ name: 'status', path: '/status' },
	{ name: 'map', path: '/map' }
];

const browser = await chromium.launch();
const problems = [];
for (const theme of themes) {
	for (const width of widths) {
		const ctx = await browser.newContext({
			viewport: { width, height: 900 },
			deviceScaleFactor: 2,
			colorScheme: theme
		});
		const page = await ctx.newPage();
		page.on('pageerror', (e) => problems.push(`${theme} ${width}: page error ${e.message}`));
		page.on('response', (r) => {
			if (r.url().includes('/api/') && r.status() >= 500)
				problems.push(`${theme} ${width}: ${r.status()} from ${r.url()}`);
		});
		for (const p of pages) {
			if (p.storage) {
				await page.goto(base + '/', { waitUntil: 'networkidle' });
				await page.evaluate((kv) => {
					for (const [k, v] of Object.entries(kv)) localStorage.setItem(k, v);
				}, p.storage);
			}
			await page.goto(base + p.path, { waitUntil: 'networkidle' });
			if (p.tab) {
				await page.getByRole('button', { name: p.tab, exact: true }).click();
				await page.waitForLoadState('networkidle');
			}
			await page.waitForTimeout(300);
			const { sw, iw } = await page.evaluate(() => ({
				sw: document.documentElement.scrollWidth,
				iw: window.innerWidth
			}));
			if (sw > iw) problems.push(`${p.name} ${theme} ${width}px scrolls sideways (${sw} > ${iw})`);
			// Phones and tablets get the bottom tab bar; desktop puts the links in the top bar.
			const tabbar = await page.locator('nav.tabbar').isVisible();
			if (tabbar !== width < 1100) problems.push(`${p.name} ${width}px: tab bar visible=${tabbar}`);
			await page.screenshot({ path: `${out}/${p.name}-${width}-${theme}.png`, fullPage: true });
		}
		await ctx.close();
	}
}
await browser.close();
if (problems.length) {
	console.error(problems.join('\n'));
	process.exit(1);
}
console.log(`ok: ${themes.length * widths.length * pages.length} screenshots in ${out}/`);
