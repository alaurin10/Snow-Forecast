// Which sky the backdrop shows, and the clock it follows. The layout sets `home` (the
// first location's forecast); a location page sets `page` to its own while it is open;
// the Settings preview sets `preview`. Every minute (not while the tab is hidden) the
// clock moves on and the sky is worked out again, so day turns to dusk on its own; when
// the clock runs past a forecast's hours, its owner is asked for a newer one.
import { darkPhase, DEFAULT_SKY, pastData, shownAt, skyOf, type SkyState } from './sky';
import type { Snapshot } from './types.gen';

const TICK_MS = 60_000;
/** At most one refetch per source in this long. */
const REFETCH_MS = 10 * 60_000;

type Source = 'home' | 'page';

class SkyStore {
	home = $state<Snapshot | null>(null);
	page = $state<Snapshot | null>(null);
	preview = $state<SkyState | null>(null);
	/** The clock the sky follows (ms). */
	now = $state(Date.now());

	private refetchers: Record<Source, (() => void) | null> = { home: null, page: null };
	private asked: Record<Source, number> = { home: 0, page: 0 };

	readonly live: SkyState = $derived.by(() => {
		const s = this.page ?? this.home;
		return s ? skyOf(s, this.now) : DEFAULT_SKY;
	});

	readonly current: SkyState = $derived(this.preview ?? this.live);

	/** The sky calls for dark mode (night or dusk), for Auto. */
	readonly dark: boolean = $derived(darkPhase(this.current.phase));

	/** Show a forecast; `refetch` is called (now and then) once the clock passes its end. */
	set(source: Source, snap: Snapshot | null, refetch: (() => void) | null = null) {
		this[source] = snap;
		this.refetchers[source] = snap ? refetch : null;
	}

	/** The time a snapshot's "now" is at, following the clock. */
	timeOf(snap: Snapshot): number {
		return shownAt(snap, this.now);
	}

	tick(at = Date.now()) {
		this.now = at;
		for (const source of ['home', 'page'] as const) {
			const snap = this[source];
			const refetch = this.refetchers[source];
			if (!snap || !refetch || !pastData(snap, at)) continue;
			if (at - this.asked[source] < REFETCH_MS) continue;
			this.asked[source] = at;
			refetch();
		}
	}

	/** Keep the clock running while the page is visible. Returns the stop function. */
	watch(): () => void {
		let timer: ReturnType<typeof setInterval> | null = null;
		const start = () => {
			if (timer) return;
			this.tick();
			timer = setInterval(() => this.tick(), TICK_MS);
		};
		const stop = () => {
			if (timer) clearInterval(timer);
			timer = null;
		};
		const onVis = () => (document.hidden ? stop() : start());
		if (!document.hidden) start();
		document.addEventListener('visibilitychange', onVis);
		return () => {
			stop();
			document.removeEventListener('visibilitychange', onVis);
		};
	}
}

export const skyState = new SkyStore();
