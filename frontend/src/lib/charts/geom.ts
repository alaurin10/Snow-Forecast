// Small geometry helpers shared by the charts. Pure, so they're easy to test.
import { area, line } from 'd3-shape';

export interface Margin {
	top: number;
	right: number;
	bottom: number;
	left: number;
}

/** A bar with 4 px rounded top corners, anchored on the baseline at y + h. */
export function roundedTopBar(x: number, y: number, w: number, h: number, r = 4): string {
	if (h <= 0 || w <= 0) return '';
	const rr = Math.min(r, w / 2, h);
	const b = y + h;
	return (
		`M${x},${b}V${y + rr}` +
		`Q${x},${y} ${x + rr},${y}` +
		`H${x + w - rr}` +
		`Q${x + w},${y} ${x + w},${y + rr}` +
		`V${b}Z`
	);
}

/** A line through (x, y) points, broken wherever y is null. */
export function linePath(xs: number[], ys: (number | null)[]): string {
	const pts = xs.map((x, i) => [x, ys[i]] as const);
	return (
		line<(typeof pts)[number]>()
			.defined((p) => p[1] !== null && Number.isFinite(p[1]))
			.x((p) => p[0])
			.y((p) => p[1] as number)(pts) ?? ''
	);
}

/** A band between two lines, broken wherever either edge is null. */
export function bandPath(xs: number[], lo: (number | null)[], hi: (number | null)[]): string {
	const pts = xs.map((x, i) => [x, lo[i], hi[i]] as const);
	return (
		area<(typeof pts)[number]>()
			.defined((p) => p[1] !== null && p[2] !== null)
			.x((p) => p[0])
			.y0((p) => p[1] as number)
			.y1((p) => p[2] as number)(pts) ?? ''
	);
}

/** [start, end) index runs where pred holds, e.g. night hours. */
export function runs<T>(values: T[], pred: (v: T, i: number) => boolean): [number, number][] {
	const out: [number, number][] = [];
	let start = -1;
	values.forEach((v, i) => {
		if (pred(v, i)) {
			if (start < 0) start = i;
		} else if (start >= 0) {
			out.push([start, i]);
			start = -1;
		}
	});
	if (start >= 0) out.push([start, values.length]);
	return out;
}

export const finite = (vals: (number | null | undefined)[]): number[] =>
	vals.filter((v): v is number => v !== null && v !== undefined && Number.isFinite(v));

export const maxOf = (vals: (number | null | undefined)[], floor = 0): number =>
	Math.max(floor, ...finite(vals));

export const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));
