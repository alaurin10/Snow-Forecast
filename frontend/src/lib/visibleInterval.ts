/**
 * Like setInterval, but skipped while the page is hidden (in the background, or the phone
 * locked): a tick missed then runs once as soon as the page is seen again. Returns the
 * function that stops it.
 */
export function visibleInterval(fn: () => void, ms: number): () => void {
	let missed = false;
	const id = setInterval(() => {
		if (document.hidden) missed = true;
		else fn();
	}, ms);
	const onShow = () => {
		if (document.hidden || !missed) return;
		missed = false;
		fn();
	};
	document.addEventListener('visibilitychange', onShow);
	return () => {
		clearInterval(id);
		document.removeEventListener('visibilitychange', onShow);
	};
}
