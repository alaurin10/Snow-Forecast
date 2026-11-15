import { afterEach, describe, expect, it, vi } from 'vitest';
import { visibleInterval } from './visibleInterval';

describe('visibleInterval', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});
	function fakeDocument() {
		const listeners: (() => void)[] = [];
		const doc = {
			hidden: false,
			addEventListener: (_: string, f: () => void) => listeners.push(f),
			removeEventListener: (_: string, f: () => void) => listeners.splice(listeners.indexOf(f), 1),
			show() {
				doc.hidden = false;
				listeners.forEach((f) => f());
			}
		};
		vi.stubGlobal('document', doc);
		return doc;
	}

	it('skips ticks while hidden and runs once when seen again', () => {
		vi.useFakeTimers();
		const doc = fakeDocument();
		const fn = vi.fn();
		const stop = visibleInterval(fn, 1000);
		vi.advanceTimersByTime(1000);
		expect(fn).toHaveBeenCalledTimes(1);
		doc.hidden = true;
		vi.advanceTimersByTime(5000);
		expect(fn).toHaveBeenCalledTimes(1);
		doc.show();
		expect(fn).toHaveBeenCalledTimes(2);
		// Seen again with nothing missed: nothing extra.
		doc.show();
		expect(fn).toHaveBeenCalledTimes(2);
		stop();
		vi.advanceTimersByTime(5000);
		expect(fn).toHaveBeenCalledTimes(2);
	});
});
