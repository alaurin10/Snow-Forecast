// The Webcams tab: pictures first, a camera's live video only after "Live", one at a time.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import WebcamsTab from './WebcamsTab.svelte';
import { prefs } from '../prefs.svelte';
import type { NearbyOut } from '../types.gen';

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
		expect(getByText('Cracking at ridgetop')).toBeTruthy();
		expect(getByText(/12 km away/)).toBeTruthy();
	});

	it('shows only the photos where there are no cameras, and says when there are none', () => {
		const photos = render(WebcamsTab, { cams: [], nearby: nearby(1) });
		expect(photos.container.querySelectorAll('.cam')).toHaveLength(0);
		expect(photos.container.querySelectorAll('.photos img')).toHaveLength(1);
		cleanup();
		const none = render(WebcamsTab, { cams: cams.slice(0, 1), nearby: nearby(0) });
		expect(none.getByText(/No photos in reports within/)).toBeTruthy();
	});

	it('never frames a player from another host', () => {
		const { queryByRole } = render(WebcamsTab, {
			cams: [{ name: 'Odd', url: 'https://x.example', video_url: 'https://x.example/player' }]
		});
		expect(queryByRole('button', { name: /live$/i })).toBeNull();
	});
});
