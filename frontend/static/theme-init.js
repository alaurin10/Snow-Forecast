// Sets the colour mode and theme on <html> before the app loads, so the page never
// flashes the wrong colours. The layout keeps them in step afterwards (see
// src/routes/+layout.svelte); the keys match src/lib/prefs.svelte.ts.
(function () {
	try {
		var root = document.documentElement;
		var mode = localStorage.getItem('sw.theme');
		var family = localStorage.getItem('sw.themeFamily');
		var motion = localStorage.getItem('sw.motion');
		var dark =
			mode === 'dark' ||
			(mode !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches);
		root.setAttribute('data-mode', dark ? 'dark' : 'light');
		if (family && family !== 'sky') root.setAttribute('data-theme', family);
		if (motion === 'off' || motion === 'subtle') root.setAttribute('data-motion', motion);
	} catch {
		// Blocked storage: the light default stands until the app starts.
	}
})();
