// A Svelte action for a chart's plot: a touch picks one direction after its first few
// pixels. Sideways reads the chart (the page mustn't scroll); up or down scrolls the page.
export function scrubLock(node: HTMLElement) {
	let from: { x: number; y: number } | null = null;
	let dir: 'h' | 'v' | null = null;
	const start = (e: TouchEvent) => {
		if (e.touches.length !== 1) return void (from = null);
		from = { x: e.touches[0].clientX, y: e.touches[0].clientY };
		dir = null;
	};
	const move = (e: TouchEvent) => {
		if (!from || e.touches.length !== 1) return;
		const dx = e.touches[0].clientX - from.x;
		const dy = e.touches[0].clientY - from.y;
		if (!dir) {
			if (Math.hypot(dx, dy) < 8) return;
			dir = Math.abs(dx) >= Math.abs(dy) ? 'h' : 'v';
		}
		if (dir === 'h' && e.cancelable) e.preventDefault();
	};
	const end = () => (from = null);
	node.addEventListener('touchstart', start, { passive: true });
	node.addEventListener('touchmove', move, { passive: false });
	node.addEventListener('touchend', end);
	node.addEventListener('touchcancel', end);
	return {
		destroy() {
			node.removeEventListener('touchstart', start);
			node.removeEventListener('touchmove', move);
			node.removeEventListener('touchend', end);
			node.removeEventListener('touchcancel', end);
		}
	};
}
