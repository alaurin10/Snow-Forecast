// Unexpected errors in the browser (a throw while rendering, a failed load): log them in
// full, and pass their message to +error.svelte so the next crash names itself.
import type { HandleClientError } from '@sveltejs/kit/hooks';

export const handleError: HandleClientError = ({ kind, error }) => {
	console.error(error);
	// App and framework errors (a 404, error(...)) already carry a message meant to show.
	if (kind !== 'unknown') return;
	const message = error instanceof Error ? error.message : String(error);
	return message ? { message } : undefined;
};
