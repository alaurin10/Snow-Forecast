// Which precipitation frames to fetch next (./frames.worker.ts does the fetching).
//
// Every frame of the timeline is wanted; a few are fetched at a time, and each time a
// slot frees the next one taken is whichever is nearest the time on the slider *then*.
// So dragging the slider somewhere new is served at once, with nothing to re-queue, and
// frames no longer wanted are cancelled.
import type { Planes } from './codec';
import type { AnyPlanes, LoadRequest, LoadResponse } from './frames.worker';

/** A frame to have ready: `key` names it (file and size), `at` is its place on the slider. */
export interface Want {
	key: string;
	url: string;
	/** Halve the rate plane (a phone's copy of a radar frame). */
	half: boolean;
	at: number;
	/** Fetched before anything else (the frame at rest, in full). */
	first?: boolean;
}

/** The side of a worker the loader uses (a fake stands in for it in tests). */
export interface WorkerLike {
	postMessage(msg: LoadRequest): void;
	onmessage: ((ev: MessageEvent<LoadResponse>) => void) | null;
	terminate(): void;
}

const AT_ONCE = 6;
const TRIES = 3;
/** A frame that failed every try is left alone this long, then tried again if still wanted. */
const REST_MS = 20_000;

export class FrameLoader<P extends AnyPlanes = Planes> {
	private wants = new Map<string, Want>();
	private flying = new Map<number, string>();
	private failed = new Map<string, { tries: number; until: number }>();
	private focus = 0;
	private nextId = 1;
	private timer: ReturnType<typeof setTimeout> | undefined;

	constructor(
		private worker: WorkerLike,
		/** A frame arrived. */
		private onPlanes: (key: string, planes: P) => void,
		/** Whether a frame is already on hand (so it isn't fetched again). */
		private have: (key: string) => boolean,
		private now: () => number = () => Date.now()
	) {
		worker.onmessage = (ev) => this.done(ev.data);
	}

	/** The frames to have ready, replacing the last list; fetches for others are cancelled. */
	want(list: Want[]) {
		this.wants = new Map(list.map((w) => [w.key, w]));
		for (const [id, key] of this.flying) {
			if (!this.wants.has(key)) this.worker.postMessage({ type: 'cancel', id });
		}
		for (const key of this.failed.keys()) if (!this.wants.has(key)) this.failed.delete(key);
		this.pump();
	}

	/** Where the slider is: frames nearest it come first. */
	seek(at: number) {
		this.focus = at;
		this.pump();
	}

	/** Frames wanted and not yet on hand. */
	get pending(): number {
		let n = 0;
		for (const key of this.wants.keys()) if (!this.have(key)) n++;
		return n;
	}

	private next(): Want | null {
		const flying = new Set(this.flying.values());
		const t = this.now();
		let best: Want | null = null;
		let bestD = Infinity;
		for (const w of this.wants.values()) {
			if (flying.has(w.key) || this.have(w.key)) continue;
			const f = this.failed.get(w.key);
			if (f && f.until > t) continue;
			// Ahead of the slider before the same distance behind it: that's where playing goes.
			const d = w.first ? -1 : Math.abs(w.at - this.focus) + (w.at < this.focus ? 0.5 : 0);
			if (d < bestD) {
				best = w;
				bestD = d;
			}
		}
		return best;
	}

	private pump() {
		while (this.flying.size < AT_ONCE) {
			const w = this.next();
			if (!w) break;
			const id = this.nextId++;
			this.flying.set(id, w.key);
			this.worker.postMessage({ type: 'load', id, url: w.url, half: w.half });
		}
		// Something is resting after its failures: look again when the first is due.
		clearTimeout(this.timer);
		const t = this.now();
		const due = [...this.failed.entries()]
			.filter(([key, f]) => f.until > t && this.wants.has(key) && !this.have(key))
			.map(([, f]) => f.until);
		if (due.length) this.timer = setTimeout(() => this.pump(), Math.min(...due) - t + 10);
	}

	private done(r: LoadResponse) {
		const key = this.flying.get(r.id);
		this.flying.delete(r.id);
		if (key === undefined) return;
		if (r.ok) {
			this.failed.delete(key);
			if (this.wants.has(key)) this.onPlanes(key, r.planes as P);
		} else if (!r.aborted) {
			const tries = (this.failed.get(key)?.tries ?? 0) + 1;
			// A quick second and third try, then a rest: never "failed for good".
			const wait = tries >= TRIES ? REST_MS : 400 * tries;
			this.failed.set(key, { tries: tries >= TRIES ? 0 : tries, until: this.now() + wait });
		}
		this.pump();
	}

	dispose() {
		clearTimeout(this.timer);
		for (const id of this.flying.keys()) this.worker.postMessage({ type: 'cancel', id });
		this.wants.clear();
		this.flying.clear();
		this.worker.onmessage = null;
		this.worker.terminate();
	}
}

/** The real worker. */
export function frameWorker(): WorkerLike {
	return new Worker(new URL('./frames.worker.ts', import.meta.url), {
		type: 'module'
	}) as unknown as WorkerLike;
}
