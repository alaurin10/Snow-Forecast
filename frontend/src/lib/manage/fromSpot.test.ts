import { describe, expect, it } from 'vitest';
import { spotDraft } from './fromSpot';

describe('spotDraft', () => {
	it('reads the spot’s point and name', () => {
		const q = new URLSearchParams({ spot: '46.85,-121.76', name: '0.8 mi S of Mount Stuart' });
		expect(spotDraft(q)).toEqual({ name: '0.8 mi S of Mount Stuart', lat: 46.85, lon: -121.76 });
	});
	it('ignores anything incomplete or odd', () => {
		expect(spotDraft(new URLSearchParams())).toBeNull();
		expect(spotDraft(new URLSearchParams({ spot: '91,2' }))).toBeNull();
		expect(spotDraft(new URLSearchParams({ spot: 'a,b' }))).toBeNull();
		expect(spotDraft(new URLSearchParams({ spot: '1' }))).toBeNull();
	});
});
