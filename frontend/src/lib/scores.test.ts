import { describe, expect, it } from 'vitest';
import { sourceName, sourceShort } from './scores';

describe('scorecard source names', () => {
	it('names the milestone 3 consensus depths', () => {
		expect(sourceName('cons_col')).toBe('Consensus (column snow ratio)');
		expect(sourceName('cons_wb')).toBe('Consensus (rain and snow split by wet-bulb)');
		expect(sourceShort('cons_wb')).toBe('the wet-bulb consensus');
	});
});
