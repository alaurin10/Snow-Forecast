// Marks a sideways-scrolling box while more of it is hidden off the right edge, so the
// theme can fade that edge (see [data-more] in theme.css) and show there is more to swipe.
//   <div class="table-wrap" use:hscroll>…</div>
export function hscroll(node: HTMLElement) {
	const update = () => {
		const more = node.scrollLeft + node.clientWidth < node.scrollWidth - 2;
		if (more) node.dataset.more = '';
		else delete node.dataset.more;
	};
	// ResizeObserver is missing in some test environments; scrolling still updates.
	const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
	ro?.observe(node);
	if (node.firstElementChild) ro?.observe(node.firstElementChild);
	node.addEventListener('scroll', update, { passive: true });
	update();
	return {
		destroy() {
			ro?.disconnect();
			node.removeEventListener('scroll', update);
		}
	};
}
