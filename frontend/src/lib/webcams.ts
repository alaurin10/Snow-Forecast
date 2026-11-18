// Webcam players and pictures. A live video plays in place only from the hosts the
// site's Content Security Policy frames (backend/snowwatch/webcams.py reads links the
// same way; keep the two in step). The server already stores each video as its host's
// embed address; reading it again here keeps anything else out of an <iframe>.
import { safeHref, safeImage } from './links';

const YT_ID = /^[A-Za-z0-9_-]{11}$/;
const YT_CHANNEL = /^UC[A-Za-z0-9_-]{22}$/;
const NAME = /^[A-Za-z0-9_-]{1,80}$/;
const YT_HOSTS = new Set(['youtube.com', 'm.youtube.com', 'youtube-nocookie.com']);

export type Player = 'youtube' | 'brownrice' | 'camstreamer' | 'roundshot';

export interface Embed {
	player: Player;
	/** The host's own player, for an <iframe>. */
	src: string;
	/** A still to show before play, when the host has one. */
	poster?: string;
}

function parse(link: string | null | undefined): URL | null {
	const href = safeHref(link);
	return href ? new URL(href) : null;
}

const host = (u: URL) => u.hostname.toLowerCase().replace(/^www\./, '');
const segs = (u: URL) => u.pathname.split('/').filter(Boolean);

function youtube(u: URL): Embed | null {
	const h = host(u);
	const s = segs(u);
	let id: string | null = null;
	if (h === 'youtu.be') id = s[0] ?? null;
	else if (YT_HOSTS.has(h)) {
		if (s[0] === 'watch') id = u.searchParams.get('v');
		else if (s[0] === 'embed' && s[1] === 'live_stream')
			return channel(u.searchParams.get('channel'));
		else if (s.length >= 2 && ['embed', 'live', 'shorts', 'v'].includes(s[0])) id = s[1];
		else if (s.length >= 3 && s[0] === 'channel' && s[2] === 'live') return channel(s[1]);
	}
	if (!id || !YT_ID.test(id)) return null;
	return {
		player: 'youtube',
		src: `https://www.youtube-nocookie.com/embed/${id}`,
		poster: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`
	};
}

function channel(ch: string | null): Embed | null {
	if (!ch || !YT_CHANNEL.test(ch)) return null;
	return { player: 'youtube', src: `https://www.youtube.com/embed/live_stream?channel=${ch}` };
}

function brownrice(u: URL): Embed | null {
	const h = host(u);
	const s = segs(u);
	let name: string | null = null;
	if (h === 'player.brownrice.com' && s.length === 2 && (s[0] === 'embed' || s[0] === 'snapshot'))
		name = s[1];
	else if (/^live\d+p?\.brownrice\.com$/.test(h)) name = u.searchParams.get('sn');
	if (!name || !NAME.test(name)) return null;
	return {
		player: 'brownrice',
		src: `https://player.brownrice.com/embed/${name}`,
		poster: `https://player.brownrice.com/snapshot/${name}`
	};
}

function camstreamer(u: URL): Embed | null {
	const s = segs(u);
	if (host(u) !== 'camstreamer.com' || s.length !== 2 || s[0] !== 'embed' || !NAME.test(s[1]))
		return null;
	return { player: 'camstreamer', src: `https://camstreamer.com/embed/${s[1]}` };
}

function roundshot(u: URL): Embed | null {
	if (u.protocol !== 'https:' || u.port || !u.hostname.toLowerCase().endsWith('.roundshot.com'))
		return null;
	u.hash = '';
	return { player: 'roundshot', src: u.href };
}

/** The player for a link to a supported webcam host, or null. */
export function embedFor(link: string | null | undefined): Embed | null {
	const u = parse(link);
	if (!u) return null;
	for (const read of [youtube, brownrice, camstreamer, roundshot]) {
		const got = read(u);
		if (got) return got;
	}
	return null;
}

/** The address the player loads once a visitor presses play. */
export function playSrc(e: Embed): string {
	if (e.player !== 'youtube') return e.src;
	const u = new URL(e.src);
	// Muted: browsers only start a video on their own when it is silent (and webcams are).
	for (const [k, v] of Object.entries({ autoplay: '1', mute: '1', playsinline: '1', rel: '0' }))
		u.searchParams.set(k, v);
	return u.href;
}

/** A picture's address with a marker that changes every few minutes, so a refresh
 *  fetches the camera's newest picture rather than the browser's copy. */
export function freshImage(url: string | null | undefined, tick: number): string | undefined {
	const href = safeImage(url);
	if (!href || !tick) return href;
	const u = new URL(href);
	u.searchParams.set('_sw', String(tick));
	return u.href;
}
