// Page controls that can dock into the app header once the page's own copy has
// scrolled out of view (desktop only). A page sets `snippet` while it is mounted
// and flips `show`; the layout swaps the main nav for the snippet with a fade.
import type { Snippet } from 'svelte';

export const pageBar = $state<{ snippet: Snippet | null; show: boolean }>({
	snippet: null,
	show: false
});
