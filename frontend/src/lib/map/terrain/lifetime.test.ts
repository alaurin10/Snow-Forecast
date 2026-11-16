// The terrain worker lasts while a map holds it: none before or after, a fresh one next time.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

class FakeWorker {
	static made: FakeWorker[] = [];
	onmessage: ((ev: MessageEvent) => void) | null = null;
	posted: unknown[] = [];
	terminated = false;
	constructor() {
		FakeWorker.made.push(this);
	}
	postMessage(m: unknown) {
		this.posted.push(m);
	}
	terminate() {
		this.terminated = true;
	}
}

describe('the terrain worker’s lifetime', () => {
	beforeEach(() => {
		FakeWorker.made = [];
		vi.resetModules();
		vi.stubGlobal('Worker', FakeWorker);
		vi.stubGlobal(
			'OffscreenCanvas',
			class {
				getContext() {
					return {};
				}
			}
		);
		vi.stubGlobal('createImageBitmap', () => Promise.resolve({}));
	});
	afterEach(() => vi.unstubAllGlobals());

	it('exists only while a map holds it', async () => {
		const { retainTerrain, terrainClient } = await import('./client');
		expect(terrainClient()).toBeNull();
		const release = retainTerrain();
		const c = terrainClient();
		expect(c).not.toBeNull();
		expect(terrainClient()).toBe(c);
		expect(FakeWorker.made).toHaveLength(1);

		// Something still waiting when the map closes fails as aborted.
		const pending = c!.point(47, -121);
		release();
		expect(FakeWorker.made[0].terminated).toBe(true);
		await expect(pending).rejects.toThrow('Aborted');
		expect(terrainClient()).toBeNull();
		release(); // twice: no harm

		// The next map gets a fresh worker.
		const again = retainTerrain();
		expect(terrainClient()).not.toBe(c);
		expect(FakeWorker.made).toHaveLength(2);
		again();
	});

	it('stays while another map still holds it', async () => {
		const { retainTerrain, terrainClient } = await import('./client');
		const a = retainTerrain();
		const b = retainTerrain();
		const c = terrainClient();
		a();
		expect(terrainClient()).toBe(c);
		expect(FakeWorker.made[0].terminated).toBe(false);
		b();
		expect(FakeWorker.made[0].terminated).toBe(true);
	});

	it('makes the job worker only when it’s asked for, and stops both together', async () => {
		const { jobsClient, retainTerrain, sendZone, terrainClient } = await import('./client');
		expect(jobsClient()).toBeNull();
		const release = retainTerrain();
		const tiles = terrainClient()!;
		// A zone for the overlay tiles doesn't start the job worker.
		sendZone('z1', [[[[0, 0]]]], 'geom1');
		expect(FakeWorker.made).toHaveLength(1);
		const jobs = jobsClient()!;
		expect(jobs).not.toBe(tiles);
		expect(FakeWorker.made).toHaveLength(2);
		// Now it's running, zones go to both, each once per outline.
		sendZone('z1', [[[[0, 0]]]], 'geom1');
		sendZone('z1', [[[[0, 0]]]], 'geom1');
		const zones = (w: FakeWorker) =>
			w.posted.filter((m) => (m as { type: string }).type === 'zone').length;
		expect(zones(FakeWorker.made[0])).toBe(1);
		expect(zones(FakeWorker.made[1])).toBe(1);
		sendZone('z1', [[[[1, 1]]]], 'geom2');
		expect(zones(FakeWorker.made[0])).toBe(2);
		release();
		expect(FakeWorker.made.every((w) => w.terminated)).toBe(true);
		expect(jobsClient()).toBeNull();
	});
});
