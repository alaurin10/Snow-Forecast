// Webcam players and pictures. A live video plays in place only from the hosts the
// site's Content Security Policy frames (backend/snowwatch/webcams.py reads links the
// same way; keep the two in step). The server already stores each video as its host's
// embed address; reading it again here keeps anything else out of an <iframe>.
import { safeHref, safeImage } from './links';
import { monthDay, weekday } from './time';

const YT_ID = /^[A-Za-z0-9_-]{11}$/;
const YT_CHANNEL = /^UC[A-Za-z0-9_-]{22}$/;
const NAME = /^[A-Za-z0-9_-]{1,80}$/;
const YT_HOSTS = new Set(['youtube.com', 'm.youtube.com', 'youtube-nocookie.com']);
const OZOLIO_ID = /^EMB_[A-Z0-9]{4,40}$/;

export type Player = 'youtube' | 'brownrice' | 'camstreamer' | 'roundshot' | 'ozolio';

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

function ozolio(u: URL): Embed | null {
	const oid = u.searchParams.get('oid');
	if (host(u) !== 'relay.ozolio.com' || u.pathname !== '/pub.api' || !oid || !OZOLIO_ID.test(oid))
		return null;
	const at = (cmd: string) => `https://relay.ozolio.com/pub.api?cmd=${cmd}&oid=${oid}`;
	return { player: 'ozolio', src: at('embed'), poster: at('poster') };
}

/** The player for a link to a supported webcam host, or null. */
export function embedFor(link: string | null | undefined): Embed | null {
	const u = parse(link);
	if (!u) return null;
	for (const read of [youtube, brownrice, camstreamer, roundshot, ozolio]) {
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

/** The calendar date ("2026-11-18") of an instant in `tz` (the location's zone). */
export function localDate(iso: string, tz?: string | null): string {
	return new Intl.DateTimeFormat('en-CA', {
		timeZone: tz ?? undefined,
		year: 'numeric',
		month: '2-digit',
		day: '2-digit'
	}).format(new Date(iso));
}

/** Items with a `time`, grouped by their local date, newest day first, each day keeping
 *  the items' order. `label` is "Today", "Yesterday" or "Tue Nov 17". */
export function byDay<T>(
	items: T[],
	time: (t: T) => string,
	tz?: string | null,
	now: number = Date.now()
): { date: string; label: string; items: T[] }[] {
	const today = localDate(new Date(now).toISOString(), tz);
	const yesterday = localDate(new Date(now - 86_400_000).toISOString(), tz);
	const days = new Map<string, T[]>();
	for (const it of items) {
		const d = localDate(time(it), tz);
		days.set(d, [...(days.get(d) ?? []), it]);
	}
	return [...days.entries()]
		.sort(([a], [b]) => (a < b ? 1 : -1))
		.map(([date, list]) => ({
			date,
			label:
				date === today
					? 'Today'
					: date === yesterday
						? 'Yesterday'
						: `${weekday(date)} ${monthDay(date)}`,
			items: list
		}));
}
