// The Webcams tab: pictures first, a camera's live video only after "Live", one at a time.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { flushSync } from 'svelte';
import WebcamsTab from './WebcamsTab.svelte';
import { prefs } from '../prefs.svelte';

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

	it('never frames a player from another host', () => {
		const { queryByRole } = render(WebcamsTab, {
			cams: [{ name: 'Odd', url: 'https://x.example', video_url: 'https://x.example/player' }]
		});
		expect(queryByRole('button', { name: /live$/i })).toBeNull();
	});
});
