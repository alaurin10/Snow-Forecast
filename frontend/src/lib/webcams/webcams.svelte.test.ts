// The Webcams tab: pictures first, a camera's live video only after "Live", one at a time.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import WebcamsTab from './WebcamsTab.svelte';
import { prefs } from '../prefs.svelte';
import type { NearbyOut } from '../types.gen';

// The viewer gets a history entry of its own; outside the app's router, a stand-in.
const nav = vi.hoisted(() => ({ state: {} as { photo?: boolean }, pushes: 0 }));
vi.mock('$app/navigation', () => ({
	pushState: (_url: string, state: { photo?: boolean }) => {
		nav.pushes++;
		nav.state = state;
	}
}));
vi.mock('$app/state', () => ({
	page: {
		get state() {
			return nav.state;
		}
	}
}));

const CLOUD = 'https://res.cloudinary.com/avcan-min/image/upload/';
const nearby = (photos: number): NearbyOut => ({
	location_id: 'whistler',
	radius_km: 60,
	stations_at: null,
	stations: [],
	reports_at: '2026-11-18T18:00:00+00:00',
	reports_days: 14,
	reports: [],
	photo_reports: photos
		? [
				{
					distance_km: 12.4,
					report: {
						id: 'r1',
						title: 'Wind slab on Blackcomb',
						time: '2026-11-18T18:00+00:00',
						region: 'Sea To Sky',
						kinds: ['snowpack'],
						images: photos,
						url: 'https://avalanche.ca/mountain-information-network/submissions/r1',
						photos: Array.from({ length: photos }, (_, i) => ({
							url: `${CLOUD}c_limit,w_1600/p${i}.jpg`,
							thumb: `${CLOUD}c_limit,w_480/p${i}.jpg`,
							caption: i ? '' : 'Cracking at ridgetop'
						}))
					}
				}
			]
		: []
});

/** A pointer drag across `el` from one point to another, as a swipe. */
function drag(el: HTMLElement, from: [number, number], to: [number, number]) {
	const ev = (type: string, [x, y]: [number, number]) =>
		el.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 }));
	ev('pointerdown', from);
	ev('pointermove', [(from[0] + to[0]) / 2, (from[1] + to[1]) / 2]);
	ev('pointermove', to);
	ev('pointerup', to);
	flushSync();
}

afterEach(() => {
	cleanup();
	prefs.setCamsAutoplay(false);
});

const cams = [
	{
		name: 'Paradise',
		url: 'https://www.nps.gov/mora/learn/photosmultimedia/webcams.htm',
		image_url: 'https://www.nps.gov/webcams-mora/mountain.jpg'
	},
	{
		name: 'Summit West',
		url: 'https://www.summitatsnoqualmie.com/webcams',
		video_url: 'https://www.youtube-nocookie.com/embed/vhO8nNqg9iw'
	},
	{
		name: 'Peak',
		url: 'https://www.whistlerblackcomb.com/',
		video_url: 'https://player.brownrice.com/embed/whistlerpeak'
	}
];

describe('webcams tab', () => {
	it('shows pictures and loads no player until Live is pressed', () => {
		const { container, getAllByRole } = render(WebcamsTab, { cams });
		expect(container.querySelectorAll('iframe')).toHaveLength(0);
		const srcs = [...container.querySelectorAll('img')].map((i) => i.getAttribute('src'));
		expect(srcs).toEqual([
			'https://www.nps.gov/webcams-mora/mountain.jpg',
			'https://i.ytimg.com/vi/vhO8nNqg9iw/hqdefault.jpg',
			'https://player.brownrice.com/snapshot/whistlerpeak'
		]);
		// Only the cameras with video get a Live button; every camera links to its site.
		expect(getAllByRole('button', { name: /live$/i })).toHaveLength(2);
		expect(getAllByRole('link', { name: /open site/i })).toHaveLength(3);
	});

	it('plays one camera at a time across the whole row, and stops', async () => {
		const { container, getByRole } = render(WebcamsTab, { cams });
		await fireEvent.click(getByRole('button', { name: 'Play Summit West live' }));
		flushSync();
		let frames = container.querySelectorAll('iframe');
		expect(frames).toHaveLength(1);
		expect(frames[0].getAttribute('src')).toContain(
			'https://www.youtube-nocookie.com/embed/vhO8nNqg9iw?'
		);
		expect(frames[0].getAttribute('sandbox')).not.toContain('allow-top-navigation');
		await fireEvent.click(getByRole('button', { name: 'Play Peak live' }));
		flushSync();
		frames = container.querySelectorAll('iframe');
		expect(frames).toHaveLength(1);
		expect(frames[0].getAttribute('src')).toBe('https://player.brownrice.com/embed/whistlerpeak');
		expect(frames[0].closest('.cam')?.classList.contains('wide')).toBe(true);
		await fireEvent.click(getByRole('button', { name: 'Stop' }));
		flushSync();
		expect(container.querySelectorAll('iframe')).toHaveLength(0);
	});

	it('plays every camera on "Play all live", and remembers it on this device', async () => {
		const { container, getByRole } = render(WebcamsTab, { cams });
		await fireEvent.click(getByRole('button', { name: 'Play all live (2)' }));
		flushSync();
		expect(container.querySelectorAll('iframe')).toHaveLength(2);
		expect(container.querySelector('.wide')).toBeNull(); // side by side when several play
		expect(prefs.camsAutoplay).toBe('on');
		expect(localStorage.getItem('sw.camsAutoplay')).toBe('on');
		cleanup();

		// The next visit starts them by itself, until "Stop all".
		const again = render(WebcamsTab, { cams });
		flushSync();
		expect(again.container.querySelectorAll('iframe')).toHaveLength(2);
		await fireEvent.click(again.getByRole('button', { name: 'Stop all' }));
		flushSync();
		expect(again.container.querySelectorAll('iframe')).toHaveLength(0);
		expect(prefs.camsAutoplay).toBe('off');
	});

	it('shows a single camera across the whole row', () => {
		const { container } = render(WebcamsTab, { cams: cams.slice(0, 1) });
		expect(container.querySelector('.cam.wide')).not.toBeNull();
		expect(container.querySelector('.bar')).toBeNull(); // no "Play all" for one camera
	});

	it('shows recent field photos below the cameras, linking each to its large copy', () => {
		const { container, getByText } = render(WebcamsTab, {
			cams: cams.slice(0, 1),
			nearby: nearby(2),
			units: 'metric',
			tz: 'America/Vancouver'
		});
		expect(getByText('Recent field photos')).toBeTruthy();
		const report = getByText('Wind slab on Blackcomb') as HTMLAnchorElement;
		expect(report.href).toContain('avalanche.ca/mountain-information-network/submissions/r1');
		const imgs = [...container.querySelectorAll('.photos img')];
		expect(imgs.map((i) => i.getAttribute('src'))).toEqual([
			`${CLOUD}c_limit,w_480/p0.jpg`,
			`${CLOUD}c_limit,w_480/p1.jpg`
		]);
		expect(imgs[0].closest('a')?.getAttribute('href')).toBe(`${CLOUD}c_limit,w_1600/p0.jpg`);
		// One short line above the photos; captions wait for the full-screen viewer.
		expect(getByText(/· 12 km$/)).toBeTruthy();
		expect(container.querySelector('figcaption')).toBeNull();
	});

	it('shows only the photos where there are no cameras, and says when there are none', () => {
		const photos = render(WebcamsTab, { cams: [], nearby: nearby(1) });
		expect(photos.container.querySelectorAll('.cam')).toHaveLength(0);
		expect(photos.container.querySelectorAll('.photos img')).toHaveLength(1);
		cleanup();
		const none = render(WebcamsTab, { cams: cams.slice(0, 1), nearby: nearby(0) });
		expect(none.getByText(/No photos within 12 mi of this location/)).toBeTruthy();
	});

	it('links NWAC’s observations for its locations, even with no cameras or photos', () => {
		const { getByRole, queryByText } = render(WebcamsTab, {
			cams: [],
			nearby: null,
			avy: { provider: 'nac', center_id: 'NWAC' }
		});
		const link = getByRole('link', { name: 'NWAC observations ↗' });
		expect(link.getAttribute('href')).toBe('https://nwac.us/observations#/view/observations');
		expect(queryByText(/can't be shown here/)).toBeNull(); // NWAC's photos are shown
		expect(queryByText(/No photos in/)).toBeNull(); // not loaded yet
		cleanup();
		const bc = render(WebcamsTab, { cams: [], nearby: nearby(1), avy: { provider: 'avcan' } });
		expect(bc.queryByRole('link', { name: /NWAC observations/ })).toBeNull();
		cleanup();
		// Centers whose photos can't be read are still only linked.
		const sierra = render(WebcamsTab, {
			cams: [],
			nearby: null,
			avy: { provider: 'nac', center_id: 'SAC' }
		});
		expect(sierra.getByRole('link', { name: 'Sierra Avalanche Center observations ↗' }));
		expect(sierra.getByText(/can't be shown here/)).toBeTruthy();
	});

	it('shows NWAC observations’ photos by the day observed, with who sent them', () => {
		const MEDIA = 'https://avalanche-org-media.s3.us-west-2.amazonaws.com/';
		const data: NearbyOut = {
			...nearby(0),
			location_id: 'crystal',
			photo_reports: [
				{
					distance_km: 2.1,
					report: {
						id: 'nwac-1',
						title: 'Silver Basin',
						time: '2026-11-24T20:00+00:00',
						day: '2026-11-24',
						region: 'West Slopes South',
						kinds: ['snowpack'],
						images: 1,
						url: 'https://nwac.us/observations/#/view/observations/1',
						source: 'nwac',
						center: 'NWAC',
						observer: 'forecaster',
						photos: [{ url: `${MEDIA}a-large.jpg`, thumb: `${MEDIA}a-medium.jpg`, caption: '' }]
					}
				}
			]
		};
		const { container, getByText, queryByText } = render(WebcamsTab, {
			cams: [],
			nearby: data,
			units: 'metric',
			tz: 'America/Los_Angeles',
			avy: { provider: 'nac', center_id: 'NWAC' }
		});
		expect(getByText(/^NWAC observations, last 14 days\./)).toBeTruthy();
		expect(queryByText(/Avalanche Canada/)).toBeNull();
		// One short line: the day only (NWAC's observations have no time of day) and how far.
		expect(getByText('Tue Nov 24 · 2 km')).toBeTruthy();
		expect(container.querySelector('.photos img')?.getAttribute('src')).toBe(
			`${MEDIA}a-medium.jpg`
		);
		const title = getByText('Silver Basin') as HTMLAnchorElement;
		expect(title.href).toBe('https://nwac.us/observations/#/view/observations/1');
	});

	it('never frames a player from another host', () => {
		const { queryByRole } = render(WebcamsTab, {
			cams: [{ name: 'Odd', url: 'https://x.example', video_url: 'https://x.example/player' }]
		});
		expect(queryByRole('button', { name: /live$/i })).toBeNull();
	});

	it('flips through every photo full screen, with where, who and the caption', async () => {
		const data: NearbyOut = {
			...nearby(2),
			zone_name: 'Sea To Sky',
			photo_reports: [
				{ ...nearby(2).photo_reports![0], group: 'near' },
				{
					distance_km: 30,
					group: 'zone',
					report: {
						...nearby(1).photo_reports![0].report,
						id: 'r2',
						title: 'Cornices on Cayoosh',
						photos: [{ url: `${CLOUD}z.jpg`, thumb: `${CLOUD}zt.jpg`, caption: 'Big cornice' }]
					}
				}
			]
		};
		nav.state = {};
		const { container, getByRole, getByText, queryByRole } = render(WebcamsTab, {
			cams: [],
			nearby: data,
			units: 'metric',
			tz: 'America/Vancouver',
			name: 'Whistler'
		});
		// Near the location first; the rest of the zone folded below.
		const more = container.querySelector('details.zone') as HTMLDetailsElement;
		expect(more.open).toBe(false);
		expect(more.textContent).toContain('More in Sea To Sky');

		// A photo opens the viewer at that photo, not a new page.
		const second = container.querySelectorAll('.photos .grid a')[1] as HTMLAnchorElement;
		const click = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
		second.dispatchEvent(click);
		flushSync();
		expect(click.defaultPrevented).toBe(true);
		expect(nav.pushes).toBe(1);
		const dialog = getByRole('dialog', { name: 'Field photos' });
		expect(getByText('2 of 3')).toBeTruthy();
		expect(dialog.querySelector('img')?.getAttribute('src')).toBe(`${CLOUD}c_limit,w_1600/p1.jpg`);
		expect(dialog.textContent).toContain('Wind slab on Blackcomb');
		expect(dialog.textContent).toContain('Avalanche Canada MIN');
		expect(dialog.textContent).toContain('12 km away · Sea To Sky');

		// Next goes on into the zone's photos, with their own caption; it wraps around.
		await fireEvent.click(getByRole('button', { name: 'Next photo' }));
		expect(getByText('3 of 3')).toBeTruthy();
		expect(getByText('Big cornice', { selector: '.caption' })).toBeTruthy();
		expect(dialog.textContent).toContain('Cornices on Cayoosh');
		await fireEvent.keyDown(window, { key: 'ArrowRight' });
		expect(getByText('1 of 3')).toBeTruthy();
		expect(getByText('Cracking at ridgetop', { selector: '.caption' })).toBeTruthy();
		await fireEvent.keyDown(window, { key: 'ArrowLeft' });
		expect(getByText('3 of 3')).toBeTruthy();

		// A swipe flips: the photo follows the finger, then the next one slides in.
		const stage = dialog.querySelector('.stage') as HTMLElement;
		drag(stage, [200, 300], [80, 310]);
		expect(getByText('1 of 3')).toBeTruthy();
		expect(dialog.querySelector('.photo')?.classList.contains('from-right')).toBe(true);
		drag(stage, [100, 300], [220, 290]);
		expect(getByText('3 of 3')).toBeTruthy();
		expect(dialog.querySelector('.photo')?.classList.contains('from-left')).toBe(true);
		// A small nudge doesn't.
		drag(stage, [200, 300], [215, 302]);
		expect(getByText('3 of 3')).toBeTruthy();
		// (A click right after a drag is the drag's own; a moment later the arrows work.)
		await new Promise((r) => setTimeout(r));
		// The arrows are big targets: the outer part of each side.
		const prev = getByRole('button', { name: 'Previous photo' });
		expect(prev.classList.contains('nav')).toBe(true);
		await fireEvent.click(prev);
		expect(getByText('2 of 3')).toBeTruthy();

		// Swiping down closes it.
		nav.state = {};
		drag(stage, [200, 200], [205, 360]);
		expect(queryByRole('dialog')).toBeNull();

		// Wide screens: Gallery shows every photo at once; one opens on its own.
		await fireEvent.click(getByRole('button', { name: 'Gallery' }));
		expect(getByText('3 photos')).toBeTruthy();
		const tiles = getByRole('dialog').querySelectorAll('.gallery button');
		expect(tiles).toHaveLength(3);
		await fireEvent.click(tiles[2]);
		expect(getByText('3 of 3')).toBeTruthy();
		await fireEvent.click(getByRole('button', { name: 'All photos' }));
		expect(getByText('3 photos')).toBeTruthy();
		// ✕ closes it (with no history entry to go back to here).
		nav.state = {};
		await fireEvent.click(getByRole('button', { name: 'Close photos' }));
		expect(queryByRole('dialog')).toBeNull();
		// No "view all" button: a photo is enough.
		expect(queryByRole('button', { name: /View all/ })).toBeNull();
	});

	it('opens the rest of the zone when nothing is near', () => {
		const data: NearbyOut = {
			...nearby(1),
			zone_name: 'West Slopes South',
			photo_reports: [{ ...nearby(1).photo_reports![0], group: 'zone' }]
		};
		const { container, getByText } = render(WebcamsTab, {
			cams: [],
			nearby: data,
			name: 'Crystal Mountain'
		});
		expect(getByText(/No photos within 12 mi of Crystal Mountain/)).toBeTruthy();
		expect((container.querySelector('details.zone') as HTMLDetailsElement).open).toBe(true);
	});
});
