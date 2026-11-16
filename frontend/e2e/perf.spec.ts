// The map's memory budget (docs/MAP-PLAN.md, "Performance rules"), measured: on the
// phone profile, radar playing, a pan and zoom, the slope overlay and a 3D pan. The
// browser is launched here so its processes can be measured (proportional set size of
// each Chromium process, from /proc, so Linux only). Numbers go to perf.json in the test's
// output folder and to the console, to compare before and after a change.
//
// The budget is on the page's own (renderer) process: it holds the decoded pictures,
// canvases and the map's workers, and it is the one a phone stops when memory runs out.
// The aim is RENDERER_AIM_MB; the test fails above RENDERER_MAX_MB, a guard against
// getting worse until the aim is reached. Timings are recorded, not held to anything (a
// shared CI machine is noisy). Headless Chromium draws with SwiftShader (the GPU's work on
// the CPU), so 3D is slow here and the GPU's memory counts as the GPU process's own.
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { chromium, devices, expect, test, type Page } from '@playwright/test';

/** MB the page's process should stay under at its peak (the plan's budget). */
const RENDERER_AIM_MB = 300;
/** MB above which the test fails: today's peak (~430 MB, Nov 2026) and some room. */
const RENDERER_MAX_MB = 520;

type Usage = { total: number; byType: Record<string, number> };

/** The process and its descendants. */
function tree(root: number): number[] {
	const kids = new Map<number, number[]>();
	for (const name of readdirSync('/proc')) {
		if (!/^\d+$/.test(name)) continue;
		try {
			// pid (comm) state ppid …; comm may hold spaces and brackets.
			const stat = readFileSync(`/proc/${name}/stat`, 'utf8');
			const ppid = Number(stat.slice(stat.lastIndexOf(')') + 2).split(' ')[1]);
			kids.set(ppid, [...(kids.get(ppid) ?? []), Number(name)]);
		} catch {
			// gone already
		}
	}
	const out: number[] = [];
	const todo = [root];
	while (todo.length) {
		const p = todo.pop()!;
		out.push(p);
		todo.push(...(kids.get(p) ?? []));
	}
	return out;
}

/** Each Chromium process's proportional set size in MB, by its --type (browser if none). */
function usage(root: number): Usage {
	const byType: Record<string, number> = {};
	let total = 0;
	for (const pid of tree(root)) {
		try {
			const pss = /^Pss:\s+(\d+) kB/m.exec(readFileSync(`/proc/${pid}/smaps_rollup`, 'utf8'));
			if (!pss) continue;
			const cmd = readFileSync(`/proc/${pid}/cmdline`, 'utf8');
			const type = /--type=([\w-]+)/.exec(cmd)?.[1] ?? 'browser';
			const mb = Number(pss[1]) / 1024;
			byType[type] = (byType[type] ?? 0) + mb;
			total += mb;
		} catch {
			// gone already
		}
	}
	return { total, byType };
}

const round = (n: number) => Math.round(n * 10) / 10;

async function mark(page: Page, name: string) {
	await expect
		.poll(() => page.evaluate((n) => performance.getEntriesByName(n).length, name), {
			timeout: 30_000
		})
		.toBeGreaterThan(0);
	return page.evaluate((n) => Math.round(performance.getEntriesByName(n)[0].startTime), name);
}

/** How long drawing a frame for the view took (map:draw, precipOverlay.ts): the median
 *  and the slowest, in ms. */
async function drawTimes(page: Page) {
	const ms = await page.evaluate(() =>
		performance.getEntriesByName('map:draw').map((m) => m.duration)
	);
	ms.sort((a, b) => a - b);
	return {
		frames_drawn: ms.length,
		draw_median_ms: round(ms[Math.floor(ms.length / 2)] ?? 0),
		draw_max_ms: round(ms[ms.length - 1] ?? 0)
	};
}

/** Drag the map by (dx, dy) in a few steps, from the middle of the screen. */
async function drag(page: Page, dx: number, dy: number) {
	const vp = page.viewportSize()!;
	const x = vp.width / 2;
	const y = vp.height / 2;
	await page.mouse.move(x, y);
	await page.mouse.down();
	await page.mouse.move(x + dx, y + dy, { steps: 8 });
	await page.mouse.up();
}

test('the map stays within its memory budget on a phone', async ({ baseURL }, info) => {
	test.skip(info.project.name !== 'phone', 'measured on the phone profile');
	test.skip(process.platform !== 'linux', 'reads /proc');
	test.setTimeout(180_000);

	const server = await chromium.launchServer();
	const root = server.process().pid!;
	const browser = await chromium.connect(server.wsEndpoint());
	/** The highest each process type (and the total) reached, each at its own moment. */
	const peak: Record<string, number> = {};
	const steps: Record<string, Usage> = {};
	const sample = () => {
		const u = usage(root);
		for (const [k, v] of [...Object.entries(u.byType), ['total', u.total] as const])
			peak[k] = Math.max(peak[k] ?? 0, v);
		return u;
	};
	const timer = setInterval(sample, 250);
	try {
		const context = await browser.newContext({ ...devices['Pixel 7'], baseURL });
		// The slope overlay on from the start: the worst case is everything at once.
		await context.addInitScript(() => localStorage.setItem('sw.mapOverlay', 'slope'));
		/** Map tiles and elevation asked for, by kind: fewer kept in memory mustn't mean
		 *  more fetched again. */
		const requests: Record<string, number> = {};
		context.on('request', (r) => {
			const u = r.url();
			const kind = u.includes('/api/tiles/')
				? 'tiles'
				: /mapterhorn|elevation-tiles/.test(u)
					? 'elevation'
					: u.includes('/api/precip/')
						? 'precip'
						: null;
			if (kind) requests[kind] = (requests[kind] ?? 0) + 1;
		});
		const page = await context.newPage();
		const cdp = await context.newCDPSession(page);
		await cdp.send('Performance.enable');
		let heapPeak = 0;
		const heap = async () => {
			const { metrics } = await cdp.send('Performance.getMetrics');
			const used = metrics.find((m) => m.name === 'JSHeapUsedSize')?.value ?? 0;
			heapPeak = Math.max(heapPeak, used / 2 ** 20);
		};

		await page.goto('/api/health');
		await page.waitForTimeout(1000);
		steps.blank = sample();
		await page.goto('/map?loc=rainy');
		const load = await mark(page, 'map:load');
		const frame = await mark(page, 'map:frame');
		steps.open = sample();

		// Radar playing (it may have started by itself).
		const play = page.getByRole('button', { name: 'Play' });
		if (await play.isVisible()) await play.click();
		await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible();
		for (let i = 0; i < 8; i++) {
			await page.waitForTimeout(500);
			await heap();
		}
		steps.playing = sample();

		// Pan and zoom, still playing.
		for (const [dx, dy] of [
			[-120, 0],
			[0, -120],
			[120, 80]
		])
			await drag(page, dx, dy);
		const vp = page.viewportSize()!;
		await page.mouse.move(vp.width / 2, vp.height / 2);
		await page.mouse.wheel(0, -400);
		await page.waitForTimeout(1500);
		await page.mouse.wheel(0, 300);
		await page.waitForTimeout(1500);
		await heap();
		steps.panned = sample();

		// 3D, then a short pan (SwiftShader makes every 3D frame slow).
		await page.getByRole('button', { name: '3D terrain' }).click();
		await expect(page.getByRole('button', { name: '3D terrain' })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		await page.waitForTimeout(4000);
		await drag(page, -100, 0);
		await page.waitForTimeout(4000);
		await heap();
		steps.threeD = sample();

		const mb = (u: Usage) => ({
			total: round(u.total),
			renderer: round(u.byType.renderer ?? 0),
			gpu: round(u.byType['gpu-process'] ?? 0)
		});
		const result = {
			project: info.project.name,
			renderer_aim_mb: RENDERER_AIM_MB,
			renderer_max_mb: RENDERER_MAX_MB,
			peak_mb: Object.fromEntries(Object.entries(peak).map(([k, v]) => [k, round(v)])),
			after_step_mb: Object.fromEntries(Object.entries(steps).map(([k, v]) => [k, mb(v)])),
			js_heap_peak_mb: round(heapPeak),
			...(await drawTimes(page)),
			map_load_ms: load,
			first_frame_ms: frame,
			requests
		};
		const out = info.outputPath('perf.json');
		writeFileSync(out, JSON.stringify(result, null, 2));
		await info.attach('perf', { path: out, contentType: 'application/json' });
		console.log('map perf', JSON.stringify(result));
		expect(peak.renderer, "peak MB of the page's process").toBeLessThan(RENDERER_MAX_MB);
	} finally {
		clearInterval(timer);
		await browser.close();
		await server.close();
	}
});
