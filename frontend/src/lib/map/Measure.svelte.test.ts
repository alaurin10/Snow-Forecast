import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import Measure from './Measure.svelte';
import Profile from './Profile.svelte';
import StationCard from './StationCard.svelte';
import ReportCard from './ReportCard.svelte';
import { expectMarksInside } from '../charts/__tests__/marks';
import type { Sample } from './measure';
import type { MapStation } from '../types.gen';

afterEach(cleanup);

/** Up 300 m over 1 km, then down a steep pitch. */
const samples: Sample[] = Array.from({ length: 81 }, (_, i) => {
	const d = i * 15;
	const elev = d <= 1000 ? 1500 + d * 0.3 : 1800 - (d - 1000) * 0.9;
	return { lon: -122 + i * 1e-4, lat: 50, d, elev, slope: d > 1000 ? 41 : 18 };
});

function props(over: Record<string, unknown> = {}) {
	return {
		title: 'Measure',
		units: 'metric' as const,
		editing: true,
		points: 3,
		samples,
		status: 'ready' as const,
		ongpx: vi.fn(),
		onclose: vi.fn(),
		onundo: vi.fn(),
		onclear: vi.fn(),
		...over
	};
}

describe('Measure', () => {
	it('shows the numbers and a profile whose marks stay inside', async () => {
		const { container, getByText } = render(Measure, props());
		expect(getByText('1.20 km')).toBeTruthy();
		expect(container.textContent).toMatch(/↑ 29\d m · ↓ 1[78]\d m/);
		expect(getByText('41°')).toBeTruthy();
		expect(container.querySelector('.profile')).toBeTruthy();
	});

	it('draws the profile inside its plot, coloured by slope, and reads it out', async () => {
		const onhover = vi.fn();
		const { container } = render(Profile, {
			samples,
			units: 'imperial',
			fixedWidth: 360,
			onhover
		});
		expectMarksInside(container);
		const segs = [...container.querySelectorAll('path.seg')].map((p) => p.getAttribute('stroke'));
		expect(segs).toEqual(['#5b6b7a', '#a8329f']);
		const hit = container.querySelector<SVGRectElement>('rect.hit')!;
		hit.getBoundingClientRect = () => ({ left: 0 }) as DOMRect;
		await fireEvent.pointerMove(hit, { clientX: 150 });
		expect(onhover).toHaveBeenCalled();
		expect(container.querySelector('.readout')?.textContent).toMatch(/ft · ground \d+°/);
	});

	it('asks for points first, and offers a GPX track', async () => {
		const p = props({ points: 1, samples: null, status: 'idle' });
		const { getByText, container } = render(Measure, p);
		expect(getByText(/one more for a line/)).toBeTruthy();
		await fireEvent.click(getByText('Undo'));
		expect(p.onundo).toHaveBeenCalled();
		const input = container.querySelector<HTMLInputElement>('input[type=file]')!;
		const file = new File(['<gpx/>'], 'a.gpx');
		Object.defineProperty(input, 'files', { value: [file] });
		await fireEvent.change(input);
		expect(p.ongpx).toHaveBeenCalledWith(file);
	});

	it('says why it couldn’t measure', () => {
		const { getByRole } = render(
			Measure,
			props({ editing: false, samples: null, status: 'failed', error: 'No track here.' })
		);
		expect(getByRole('alert').textContent).toContain('No track here.');
	});
});

describe('map panel cards', () => {
	it('shows a station’s depth, its change and its page', () => {
		const st: MapStation = {
			id: '908:WA:SNTL',
			name: 'Olallie Meadows',
			network: 'snotel',
			lat: 47.37,
			lon: -121.44,
			elev_m: 1222,
			obs_time: new Date(Date.now() - 2 * 3600000).toISOString(),
			depth_cm: 40,
			change24_cm: -3,
			daily: [10, 20, 30, 40].map((v, i) => ({ date: `2026-11-0${i + 1}`, depth_cm: v })),
			url: 'https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=908'
		};
		const { getByText, container } = render(StationCard, { station: st, units: 'metric' });
		expect(getByText('40 cm')).toBeTruthy();
		expect(getByText(/−3 cm \(settling or melt\)/)).toBeTruthy();
		expect(getByText(/2 h ago/)).toBeTruthy();
		expect(container.querySelector('path.spark')?.getAttribute('d')).toMatch(/^M0/);
		expect(getByText('Station page').getAttribute('href')).toBe(st.url);
	});

	it('shows a field report with its link, and never a bad one', () => {
		const report = {
			id: 'a',
			title: 'Whumpfing',
			time: '2026-11-11T19:00+00:00',
			region: 'Purcells',
			kinds: ['avalanche', 'snowpack'],
			images: 2,
			url: 'javascript:alert(1)'
		};
		const { getByText, queryByText } = render(ReportCard, { report });
		expect(getByText(/Purcells/)).toBeTruthy();
		expect(getByText('Avalanche')).toBeTruthy();
		expect(getByText(/2 photos/)).toBeTruthy();
		expect(queryByText(/Read it on avalanche.ca/)).toBeNull();
	});
});
