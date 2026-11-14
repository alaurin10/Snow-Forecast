// Sets the colour mode and theme on <html> before the app loads, so the page never
// flashes the wrong colours. The layout keeps them in step afterwards (see
// src/routes/+layout.svelte); the keys match src/lib/prefs.svelte.ts.
(function () {
	try {
		var root = document.documentElement;
		var mode = localStorage.getItem('sw.theme');
		var family = localStorage.getItem('sw.themeFamily');
		var motion = localStorage.getItem('sw.motion');
		// Auto with Live Sky goes dark from dusk until dawn: the app saves whether the sky
		// was dark (and when) in sw.skyDark; trust it for two hours (SKY_DARK_TTL_MS in
		// src/lib/mode.svelte.ts).
		var hint = (localStorage.getItem('sw.skyDark') || '').split(':');
		var skyDark =
			(!family || family === 'sky') &&
			hint[0] === '1' &&
			Date.now() - Number(hint[1]) < 2 * 3600 * 1000;
		var dark =
			mode === 'dark' ||
			(mode !== 'light' &&
				(skyDark || window.matchMedia('(prefers-color-scheme: dark)').matches));
		root.setAttribute('data-mode', dark ? 'dark' : 'light');
		if (family && family !== 'sky') root.setAttribute('data-theme', family);
		if (motion === 'off' || motion === 'subtle') root.setAttribute('data-motion', motion);
	} catch {
		// Blocked storage: the light default stands until the app starts.
	}
})();
