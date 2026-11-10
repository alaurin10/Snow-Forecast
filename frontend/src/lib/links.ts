// Links to other sites come from the server, which already checks them; this is a
// second guard so an unexpected value (an old cached response, say) can never put a
// `javascript:` address in an href or src.

/** The link if it is a plain http(s) address, else undefined (which renders no href). */
export function safeHref(url: string | null | undefined): string | undefined {
	if (!url) return undefined;
	try {
		const u = new URL(url);
		return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : undefined;
	} catch {
		return undefined;
	}
}

/** Images on an https page must be https themselves, or the browser blocks them. */
export function safeImage(url: string | null | undefined): string | undefined {
	const href = safeHref(url);
	return href?.startsWith('https:') ? href : undefined;
}
