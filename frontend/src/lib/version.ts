// Which version of Snow Watch is running: this app (built into the page) and the
// server (from /api/meta). They differ when the browser still runs an older copy.

export const APP_VERSION: string = __APP_VERSION__;

/** "abc1234" from a full or short commit id, or null. */
export const shortCommit = (commit: string | null | undefined): string | null =>
	commit ? commit.slice(0, 7) : null;

/** True when the server runs a different version than this page. */
export const outOfDate = (serverVersion: string | null | undefined): boolean =>
	!!serverVersion && serverVersion !== APP_VERSION;
