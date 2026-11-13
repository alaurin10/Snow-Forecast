import { describe, expect, it } from 'vitest';
import { TapGate } from './taps';

/** A gate on a clock the test moves. */
function gate() {
	let t = 1000;
	const g = new TapGate(() => t);
	const at = (ms: number) => (t += ms);
	const tap = (x = 100, y = 100) => {
		g.start(x, y, 1);
		at(60);
		g.end(0);
	};
	const pan = () => {
		g.start(100, 100, 1);
		for (let i = 1; i <= 5; i++) {
			at(30);
			g.move(100, 100 + i * 20, 1);
		}
		g.end(0);
	};
	const pinch = () => {
		g.start(100, 100, 1);
		g.start(200, 200, 2);
		at(200);
		g.move(90, 90, 2);
		g.end(1);
		g.end(0);
	};
	return { g, at, tap, pan, pinch };
}

describe('TapGate', () => {
	it('acts on a mouse click at once', () => {
		expect(new TapGate().click()).toBe('now');
	});

	it('waits on a tap', () => {
		const { g, tap } = gate();
		tap();
		expect(g.click()).toBe('wait');
	});

	it('takes the first tap after a pan or a pinch (the bug: it used to need two)', () => {
		const s = gate();
		s.pan();
		s.at(300);
		s.tap();
		expect(s.g.click()).toBe('wait');
		const p = gate();
		p.pinch();
		p.at(300);
		p.tap();
		expect(p.g.click()).toBe('wait');
	});

	it('takes the first tap after a double-tap zoom, once the double tap is over', () => {
		const { g, at, tap } = gate();
		tap();
		expect(g.click()).toBe('wait');
		at(100);
		tap();
		expect(g.click()).toBe('drop');
		at(800);
		tap();
		expect(g.click()).toBe('wait');
	});

	it('drops the second tap of a double tap, but not a quick tap somewhere else', () => {
		const { g, at, tap } = gate();
		tap();
		g.click();
		at(150);
		tap(110, 105);
		expect(g.click()).toBe('drop');
		at(150);
		tap(300, 300);
		expect(g.click()).toBe('wait');
	});

	it('drops a click that arrives after the next touch began', () => {
		const { g, at, tap } = gate();
		tap();
		at(50);
		g.start(100, 100, 1);
		expect(g.click()).toBe('drop');
	});

	it('drops the late click of a double tap held and dragged', () => {
		const { g, at, tap } = gate();
		tap();
		at(80);
		g.start(100, 100, 1);
		for (let i = 1; i <= 4; i++) g.move(100, 100 + i * 20, 1);
		g.end(0);
		expect(g.click()).toBe('drop');
	});
});
