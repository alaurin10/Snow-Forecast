import { describe, expect, it } from 'vitest';
import { byDay, centerObservations, embedFor, freshImage, playSrc } from './webcams';

const NOCOOKIE = 'https://www.youtube-nocookie.com/embed/vhO8nNqg9iw';

describe('embedFor', () => {
	it('reads every way of linking a YouTube video', () => {
		for (const link of [
			'https://www.youtube.com/watch?v=vhO8nNqg9iw',
			'https://youtube.com/watch?v=vhO8nNqg9iw&t=3',
			'https://m.youtube.com/watch?v=vhO8nNqg9iw',
			'https://youtu.be/vhO8nNqg9iw?si=abc',
			'https://www.youtube.com/live/vhO8nNqg9iw',
			'https://www.youtube.com/embed/vhO8nNqg9iw?autoplay=1',
			NOCOOKIE
		]) {
			const e = embedFor(link);
			expect(e?.src, link).toBe(NOCOOKIE);
			expect(e?.poster).toBe('https://i.ytimg.com/vi/vhO8nNqg9iw/hqdefault.jpg');
		}
		const ch = 'UCabcdefghijklmnopqrstuv';
		expect(embedFor(`https://www.youtube.com/channel/${ch}/live`)?.src).toBe(
			`https://www.youtube.com/embed/live_stream?channel=${ch}`
		);
	});

	it('reads Brownrice, CamStreamer, Roundshot and Ozolio players', () => {
		const br = embedFor('https://live9.brownrice.com/?sn=whistlerpeak&em=1');
		expect(br).toEqual({
			player: 'brownrice',
			src: 'https://player.brownrice.com/embed/whistlerpeak',
			poster: 'https://player.brownrice.com/snapshot/whistlerpeak'
		});
		expect(embedFor('https://camstreamer.com/embed/PZyoJBnQWsgYw?enablejsapi=1')?.src).toBe(
			'https://camstreamer.com/embed/PZyoJBnQWsgYw'
		);
		expect(embedFor('https://crystal.roundshot.com/#/')?.src).toBe(
			'https://crystal.roundshot.com/'
		);
		expect(embedFor('https://relay.ozolio.com/pub.api?cmd=poster&oid=EMB_NJJN000010BA')).toEqual({
			player: 'ozolio',
			src: 'https://relay.ozolio.com/pub.api?cmd=embed&oid=EMB_NJJN000010BA',
			poster: 'https://relay.ozolio.com/pub.api?cmd=poster&oid=EMB_NJJN000010BA'
		});
	});

	it('leaves every other link as a plain link', () => {
		for (const bad of [
			'https://www.youtube.com/@TheSummitatSnoqualmie',
			'https://www.youtube.com/watch?v=short',
			'https://evil.example/embed/vhO8nNqg9iw',
			'https://youtube.com.evil.example/watch?v=vhO8nNqg9iw',
			'http://crystal.roundshot.com/',
			'https://roundshot.com.evil.example/',
			'https://www.nps.gov/webcams-mora/mountain.jpg',
			'https://relay.ozolio.com/pub.api?cmd=embed&oid=%3Cscript%3E',
			'https://relay.ozolio.com.evil.example/pub.api?cmd=embed&oid=EMB_NJJN000010BA',
			'javascript:alert(1)',
			'',
			null
		])
			expect(embedFor(bad), String(bad)).toBeNull();
	});
});

describe('playSrc', () => {
	it('starts YouTube muted and inline; other players as they are', () => {
		const yt = new URL(playSrc(embedFor(NOCOOKIE)!));
		expect(yt.origin + yt.pathname).toBe(NOCOOKIE);
		expect(yt.searchParams.get('autoplay')).toBe('1');
		expect(yt.searchParams.get('mute')).toBe('1');
		expect(yt.searchParams.get('playsinline')).toBe('1');
		const br = embedFor('https://player.brownrice.com/embed/whistlerpeak')!;
		expect(playSrc(br)).toBe(br.src);
	});
});

describe('freshImage', () => {
	it('marks a refresh, keeping the camera’s own query', () => {
		expect(freshImage('https://x.example/c.jpg?w=640', 0)).toBe('https://x.example/c.jpg?w=640');
		expect(freshImage('https://x.example/c.jpg?w=640', 42)).toBe(
			'https://x.example/c.jpg?w=640&_sw=42'
		);
		expect(freshImage('http://x.example/c.jpg', 42)).toBeUndefined();
	});
});

describe('byDay', () => {
	it('groups by the location’s calendar day, newest first, naming today and yesterday', () => {
		const now = Date.parse('2026-11-18T20:00:00Z'); // noon in Vancouver
		const items = [
			{ id: 'a', time: '2026-11-18T18:00+00:00' }, // 10 AM Pacific, today
			{ id: 'b', time: '2026-11-18T06:00+00:00' }, // 10 PM Pacific, yesterday
			{ id: 'c', time: '2026-11-17T19:00+00:00' }, // 11 AM Pacific, yesterday
			{ id: 'd', time: '2026-11-15T19:00+00:00' }
		];
		const days = byDay(items, (i) => i.time, 'America/Vancouver', now);
		expect(days.map((d) => [d.label, d.items.map((i) => i.id)])).toEqual([
			['Today', ['a']],
			['Yesterday', ['b', 'c']],
			['Sun Nov 15', ['d']]
		]);
		// In UTC the same instants fall on other days.
		expect(byDay(items, (i) => i.time, 'UTC', now)[0].items.map((i) => i.id)).toEqual(['a', 'b']);
	});
});

describe('centerObservations', () => {
	it('links the observations of the centers it knows, and no others', () => {
		expect(centerObservations({ provider: 'nac', center_id: 'NWAC' })?.url).toBe(
			'https://nwac.us/observations#/view/observations'
		);
		expect(centerObservations({ provider: 'nac', center_id: 'SAC' })?.name).toBe(
			'Sierra Avalanche Center'
		);
		expect(centerObservations({ provider: 'nac', center_id: 'uac' })?.url).toBe(
			'https://utahavalanchecenter.org/observations'
		);
		expect(centerObservations({ provider: 'nac', center_id: 'XYZ' })).toBeNull();
		expect(centerObservations({ provider: 'avcan', center_id: null })).toBeNull();
		expect(centerObservations(null)).toBeNull();
	});
});
