// App-wide connection state shown as banners in the layout.
class Session {
	/** The browser thinks it's offline; data may come from the service worker cache. */
	online = $state(typeof navigator === 'undefined' ? true : navigator.onLine);
}

export const session = new Session();
