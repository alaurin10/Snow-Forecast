// A sheet at the foot of the screen that a swipe down puts away (phones and tablets):
// from anywhere on it, once its content is scrolled to the top (or always, from its
// header). It follows the finger, and goes if pulled far enough or flicked; otherwise
// it springs back. A sideways or upward swipe is left alone (it scrolls, or taps).

export interface SwipeCloseOptions {
	onclose: () => void;
	/** The part of the sheet that scrolls, if any: a swipe down there only closes the
	 *  sheet once it's at the top. */
	scroller?: () => HTMLElement | null | undefined;
	/** Only where this media query matches (the sheet layout). */
	media?: string;
}

/** How far (px) or how fast (px/ms) a pull must be to put the sheet away. */
export const CLOSE_DISTANCE = 72;
export const CLOSE_SPEED = 0.5;

/** Whether a pull of `dy` px over `ms` milliseconds puts the sheet away. */
export function pullCloses(dy: number, ms: number, height: number): boolean {
	if (dy <= 0) return false;
	return (
		dy >= Math.min(CLOSE_DISTANCE, height * 0.35) || (dy > 16 && dy / Math.max(ms, 1) > CLOSE_SPEED)
	);
}

export function swipeClose(node: HTMLElement, opts: SwipeCloseOptions) {
	let o = opts;
	let g: { x0: number; y0: number; t0: number; mode: 'wait' | 'pull' | 'off'; dy: number } | null =
		null;

	const enabled = () => !o.media || typeof matchMedia !== 'function' || matchMedia(o.media).matches;
	const reset = (animate: boolean) => {
		node.style.transition = animate ? 'transform 200ms cubic-bezier(0.2, 0.8, 0.2, 1)' : '';
		node.style.transform = '';
	};

	const start = (e: TouchEvent) => {
		if (e.touches.length !== 1 || !enabled()) return void (g = null);
		const t = e.touches[0];
		g = { x0: t.clientX, y0: t.clientY, t0: e.timeStamp, mode: 'wait', dy: 0 };
	};
	const move = (e: TouchEvent) => {
		if (!g || g.mode === 'off' || e.touches.length !== 1) return;
		const t = e.touches[0];
		const dx = t.clientX - g.x0;
		const dy = t.clientY - g.y0;
		if (g.mode === 'wait') {
			if (Math.hypot(dx, dy) < 6) return;
			const sc = o.scroller?.();
			const inHeader = !!(e.target as Element | null)?.closest?.('header');
			const atTop = !sc || !sc.contains(e.target as Node) || sc.scrollTop <= 0;
			g.mode = dy > 0 && Math.abs(dy) > Math.abs(dx) && (inHeader || atTop) ? 'pull' : 'off';
			if (g.mode === 'off') return;
			node.style.transition = '';
		}
		g.dy = Math.max(0, dy);
		node.style.transform = `translateY(${g.dy}px)`;
		if (e.cancelable) e.preventDefault();
	};
	const end = (e: TouchEvent) => {
		if (!g) return;
		const { mode, dy, t0 } = g;
		g = null;
		if (mode !== 'pull') return;
		if (pullCloses(dy, e.timeStamp - t0, node.offsetHeight)) {
			node.style.transition = 'transform 160ms ease-in';
			node.style.transform = `translateY(${node.offsetHeight + 24}px)`;
			setTimeout(() => o.onclose(), 140);
		} else reset(true);
	};
	const cancel = () => {
		if (g?.mode === 'pull') reset(true);
		g = null;
	};

	node.addEventListener('touchstart', start, { passive: true });
	node.addEventListener('touchmove', move, { passive: false });
	node.addEventListener('touchend', end);
	node.addEventListener('touchcancel', cancel);
	return {
		update(next: SwipeCloseOptions) {
			o = next;
		},
		destroy() {
			node.removeEventListener('touchstart', start);
			node.removeEventListener('touchmove', move);
			node.removeEventListener('touchend', end);
			node.removeEventListener('touchcancel', cancel);
		}
	};
}
