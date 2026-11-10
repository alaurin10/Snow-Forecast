// Turn a failed request into a sentence a visitor can act on.
import { ApiError } from './api';

export function friendlyError(e: unknown): string {
	if (e instanceof ApiError) {
		if (e.status === 503 && e.message === 'offline')
			return 'You’re offline, and this hasn’t been saved on this device yet.';
		if (e.status === 429) return 'Too many requests just now. Wait a minute and try again.';
		if (e.status >= 500) return 'The server had a problem. Try again in a moment.';
		return e.message;
	}
	if (e instanceof TypeError) return 'Couldn’t reach the server. Check your connection.';
	return e instanceof Error ? e.message : 'Something went wrong.';
}
