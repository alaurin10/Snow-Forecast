// The More tab is now Settings: old links, bookmarks and notifications land there.
import { redirect } from '@sveltejs/kit';

export function load() {
	redirect(308, '/settings');
}
