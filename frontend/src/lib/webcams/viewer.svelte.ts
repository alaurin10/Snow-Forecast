// The full-screen photo viewer's open state, for a component that shows it. Opening it
// adds a history entry of its own (SvelteKit shallow routing), so the phone's Back button
// closes the viewer rather than leaving the page. Call during component setup.
import { pushState } from '$app/navigation';
import { page } from '$app/state';

export interface PhotoViewerState {
	/** The photo showing, or null while closed; the viewer moves it. */
	index: number | null;
	/** Open at photo `i`. Given the click, Ctrl/⌘/Shift and middle clicks are left alone
	 *  (the link opens the photo in a new tab). */
	open(i: number, e?: MouseEvent): void;
	close(): void;
}

export function photoViewer(): PhotoViewerState {
	let index = $state<number | null>(null);
	$effect(() => {
		if (!page.state.photo) index = null;
	});
	return {
		get index() {
			return index;
		},
		set index(i) {
			index = i;
		},
		open(i, e) {
			if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0)) return;
			e?.preventDefault();
			index = i;
			if (!page.state.photo) pushState('', { photo: true });
		},
		close() {
			if (page.state.photo) history.back();
			else index = null;
		}
	};
}
