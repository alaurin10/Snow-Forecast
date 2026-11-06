// Drawing kit for share images: a fixed-size canvas in a phone-photo shape, the app's
// colours read from the live theme, and the frame every card shares (header, a content
// card, the Snow Watch footer). Cards draw their own content inside the frame.

export type Shape = 'portrait' | 'landscape';

/** Phone-photo sizes: 3:4 portrait (the default) and 4:3 landscape. */
export const SIZES: Record<Shape, { w: number; h: number }> = {
	portrait: { w: 1080, h: 1440 },
	landscape: { w: 1440, h: 1080 }
};

export interface Rect {
	x: number;
	y: number;
	w: number;
	h: number;
}

export interface Palette {
	dark: boolean;
	bg: string;
	surface: string;
	surface2: string;
	border: string;
	text: string;
	text2: string;
	text3: string;
	grid: string;
	night: string;
	accent: string;
	accentSoft: string;
	snow: string;
	heavy: string;
	mix: string;
	rain: string;
	temp: string;
	level: string;
	wind: string;
	cloud: string;
}

export const FONT_UI = "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
export const FONT_NUM = `'Space Grotesk', ${FONT_UI}`;

/** The colours of the theme the app is showing right now. */
export function palette(): Palette {
	const cs = getComputedStyle(document.documentElement);
	const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
	const bg = v('--bg', '#faf7f4');
	const dark = luminance(bg) < 0.4;
	return {
		dark,
		bg,
		surface: v('--surface', '#ffffff'),
		surface2: v('--surface-2', '#f3eee9'),
		border: v('--border', '#eae3dc'),
		text: v('--text', '#1f1b2e'),
		text2: v('--text-2', '#575167'),
		text3: v('--text-3', '#6a6479'),
		grid: v('--grid', '#f1ebe5'),
		// Night shading, a touch stronger than on screen so it survives recompression.
		night: dark ? 'rgba(0, 0, 0, 0.3)' : 'rgba(31, 27, 46, 0.055)',
		accent: v('--accent', '#4b3fb5'),
		accentSoft: v('--accent-soft', '#ece8fb'),
		snow: v('--snow', '#4a8fe7'),
		heavy: v('--snow-heavy', '#dd6b20'),
		mix: v('--mix', '#9b6be0'),
		rain: v('--rain', '#26965f'),
		temp: v('--temp', '#e5484d'),
		level: v('--level', '#c2479f'),
		wind: v('--wind', '#14a3a3'),
		cloud: `rgb(${v('--cloud', '140 147 168').split(/\s+/).join(', ')})`
	};
}

/** Relative luminance of a #rrggbb colour (0 black … 1 white); 1 when unreadable. */
export function luminance(hex: string): number {
	const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
	if (!m) return 1;
	const n = parseInt(m[1], 16);
	const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
		const s = c / 255;
		return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Wait for the app's web fonts so the canvas never falls back to a system font. */
export async function ensureFonts(): Promise<void> {
	if (typeof document === 'undefined' || !document.fonts) return;
	await Promise.all(
		[
			`400 24px Inter`,
			`500 24px Inter`,
			`600 24px Inter`,
			`500 24px 'Space Grotesk'`,
			`600 24px 'Space Grotesk'`
		].map((f) => document.fonts.load(f).catch(() => []))
	);
}

export type Ctx = CanvasRenderingContext2D;

export function font(ctx: Ctx, size: number, weight = 400, num = false): void {
	ctx.font = `${weight} ${size}px ${num ? FONT_NUM : FONT_UI}`;
}

export function text(
	ctx: Ctx,
	s: string,
	x: number,
	y: number,
	color: string,
	align: CanvasTextAlign = 'left',
	baseline: CanvasTextBaseline = 'alphabetic'
): number {
	ctx.fillStyle = color;
	ctx.textAlign = align;
	ctx.textBaseline = baseline;
	ctx.fillText(s, x, y);
	return ctx.measureText(s).width;
}

/** Shorten `s` with an ellipsis until it fits in `max` px in the current font. */
export function ellipsize(ctx: Ctx, s: string, max: number): string {
	if (ctx.measureText(s).width <= max) return s;
	let lo = 0;
	let hi = s.length;
	while (lo < hi) {
		const mid = Math.ceil((lo + hi) / 2);
		if (ctx.measureText(s.slice(0, mid) + '…').width <= max) lo = mid;
		else hi = mid - 1;
	}
	return s.slice(0, lo).trimEnd() + '…';
}

/** The largest font size from `size` down to `min` at which `s` fits in `max` px. */
export function fitSize(
	ctx: Ctx,
	s: string,
	max: number,
	size: number,
	min: number,
	weight = 600,
	num = false
): number {
	let f = size;
	for (; f > min; f -= 2) {
		font(ctx, f, weight, num);
		if (ctx.measureText(s).width <= max) break;
	}
	font(ctx, f, weight, num);
	return f;
}

export function roundRect(ctx: Ctx, x: number, y: number, w: number, h: number, r: number): void {
	const rr = Math.max(0, Math.min(r, w / 2, h / 2));
	ctx.beginPath();
	ctx.moveTo(x + rr, y);
	ctx.arcTo(x + w, y, x + w, y + h, rr);
	ctx.arcTo(x + w, y + h, x, y + h, rr);
	ctx.arcTo(x, y + h, x, y, rr);
	ctx.arcTo(x, y, x + w, y, rr);
	ctx.closePath();
}

export function fillRound(
	ctx: Ctx,
	x: number,
	y: number,
	w: number,
	h: number,
	r: number,
	color: string
): void {
	roundRect(ctx, x, y, w, h, r);
	ctx.fillStyle = color;
	ctx.fill();
}

export interface Head {
	/** Small caps line above the title, e.g. "SNOW · NEXT 5 DAYS". */
	eyebrow: string;
	title: string;
	subtitle: string;
	/** Footer note on the right, e.g. when the forecast was made. */
	note: string;
}

/** The Snow Watch mark: the app icon's rounded square with a six-armed flake. */
function mark(ctx: Ctx, x: number, y: number, s: number, p: Palette): void {
	fillRound(ctx, x, y, s, s, s * 0.26, p.accent);
	const cx = x + s / 2;
	const cy = y + s / 2;
	const r = s * 0.3;
	ctx.strokeStyle = '#ffffff';
	ctx.lineWidth = Math.max(2, s * 0.075);
	ctx.lineCap = 'round';
	ctx.beginPath();
	for (let k = 0; k < 3; k++) {
		const a = (Math.PI / 3) * k + Math.PI / 2;
		ctx.moveTo(cx - r * Math.cos(a), cy - r * Math.sin(a));
		ctx.lineTo(cx + r * Math.cos(a), cy + r * Math.sin(a));
	}
	ctx.stroke();
}

/**
 * Background, header, footer and the content card. Returns the inside of the card,
 * where a card's own content goes.
 */
export function frame(ctx: Ctx, shape: Shape, head: Head, p: Palette): Rect {
	const { w, h } = SIZES[shape];
	const pad = shape === 'portrait' ? 60 : 56;
	ctx.fillStyle = p.bg;
	ctx.fillRect(0, 0, w, h);

	// Header.
	let y = pad + 26;
	font(ctx, 24, 600);
	text(ctx, ellipsize(ctx, head.eyebrow.toUpperCase(), w - pad * 2), pad, y, p.accent);
	y += 16;
	const ts = fitSize(ctx, head.title, w - pad * 2, 64, 40, 600, true);
	y += ts;
	text(ctx, ellipsize(ctx, head.title, w - pad * 2), pad, y, p.text);
	y += 42;
	font(ctx, 27, 400);
	text(ctx, ellipsize(ctx, head.subtitle, w - pad * 2), pad, y, p.text2);
	y += 30;

	// Footer.
	const fy = h - pad;
	const ms = 40;
	mark(ctx, pad, fy - ms, ms, p);
	font(ctx, 26, 600);
	text(ctx, 'Snow Watch', pad + ms + 14, fy - ms / 2, p.text, 'left', 'middle');
	font(ctx, 21, 400);
	const brandW = 14 + ms + 170;
	text(
		ctx,
		ellipsize(ctx, head.note, w - pad * 2 - brandW),
		w - pad,
		fy - ms / 2,
		p.text3,
		'right',
		'middle'
	);

	// Content card.
	const top = y + 4;
	const bottom = fy - ms - 28;
	const card = { x: pad, y: top, w: w - pad * 2, h: bottom - top };
	fillRound(ctx, card.x, card.y, card.w, card.h, 30, p.surface);
	roundRect(ctx, card.x + 0.5, card.y + 0.5, card.w - 1, card.h - 1, 30);
	ctx.strokeStyle = p.border;
	ctx.lineWidth = 1.5;
	ctx.stroke();
	const ip = shape === 'portrait' ? 36 : 34;
	return { x: card.x + ip, y: card.y + ip, w: card.w - ip * 2, h: card.h - ip * 2 };
}

export interface Stat {
	label: string;
	value: string;
	sub?: string;
	color?: string;
}

/** A row of headline numbers across the top of a card. Returns the height used. */
export function statRow(ctx: Ctx, r: Rect, stats: Stat[], p: Palette): number {
	const n = stats.length;
	const gap = 28;
	const cw = (r.w - gap * (n - 1)) / n;
	stats.forEach((s, i) => {
		const x = r.x + i * (cw + gap);
		if (i) {
			ctx.fillStyle = p.border;
			ctx.fillRect(x - gap / 2, r.y + 4, 1.5, 104);
		}
		font(ctx, 22, 600);
		if (s.color) fillRound(ctx, x, r.y + 6, 14, 14, 4, s.color);
		text(
			ctx,
			ellipsize(ctx, s.label, cw - (s.color ? 22 : 0)),
			x + (s.color ? 22 : 0),
			r.y + 20,
			p.text2
		);
		fitSize(ctx, s.value, cw, 50, 30, 600, true);
		text(ctx, s.value, x, r.y + 74, p.text);
		if (s.sub) {
			font(ctx, 22, 400);
			text(ctx, ellipsize(ctx, s.sub, cw), x, r.y + 106, p.text3);
		}
	});
	return 124;
}

export interface LegendItem {
	label: string;
	color?: string;
	/** Draw the swatch as a line (solid or dashed) instead of a block. */
	line?: 'solid' | 'dashed';
	alpha?: number;
}

/** Legend items flowing in rows from the bottom of `r` upward. Returns the height used. */
export function legend(ctx: Ctx, r: Rect, items: LegendItem[], p: Palette): number {
	font(ctx, 21, 400);
	const rowH = 34;
	const rows: { item: LegendItem; w: number }[][] = [[]];
	let used = 0;
	for (const item of items) {
		const w = (item.color ? 30 : 0) + ctx.measureText(item.label).width + 26;
		if (used + w > r.w && rows[rows.length - 1].length) {
			rows.push([]);
			used = 0;
		}
		rows[rows.length - 1].push({ item, w });
		used += w;
	}
	const top = r.y + r.h - rows.length * rowH;
	rows.forEach((row, k) => {
		let x = r.x;
		const cy = top + k * rowH + rowH / 2;
		for (const { item, w } of row) {
			if (item.color) {
				ctx.globalAlpha = item.alpha ?? 1;
				if (item.line) {
					ctx.strokeStyle = item.color;
					ctx.lineWidth = 4;
					ctx.setLineDash(item.line === 'dashed' ? [7, 5] : []);
					ctx.beginPath();
					ctx.moveTo(x, cy);
					ctx.lineTo(x + 22, cy);
					ctx.stroke();
					ctx.setLineDash([]);
				} else fillRound(ctx, x, cy - 8, 18, 16, 4, item.color);
				ctx.globalAlpha = 1;
				x += 30;
			}
			text(ctx, item.label, x, cy, p.text2, 'left', 'middle');
			x += w - (item.color ? 30 : 0);
		}
	});
	return rows.length * rowH;
}

/** Draw a card onto a fresh canvas of the chosen shape. */
export function paint(shape: Shape, draw: (ctx: Ctx, p: Palette) => void): HTMLCanvasElement {
	const { w, h } = SIZES[shape];
	const canvas = document.createElement('canvas');
	canvas.width = w;
	canvas.height = h;
	const ctx = canvas.getContext('2d');
	if (!ctx) throw new Error('Canvas is not available');
	draw(ctx, palette());
	return canvas;
}

export function toBlob(canvas: HTMLCanvasElement): Promise<Blob> {
	return new Promise((ok, fail) =>
		canvas.toBlob((b) => (b ? ok(b) : fail(new Error('Could not make the image'))), 'image/png')
	);
}

/** A file-name-safe slug: "Heather–Maple / Rainy Pass" → "heather-maple-rainy-pass". */
export function slug(s: string): string {
	return (
		s
			.normalize('NFKD')
			.replace(/[̀-ͯ]/g, '')
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '-')
			.replace(/^-+|-+$/g, '') || 'snow-watch'
	);
}

/** "Thu Nov 5, 1:34 PM" for an ISO instant, in the browser's time. */
export function madeAt(iso: string): string {
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) return '';
	return d.toLocaleString('en-US', {
		weekday: 'short',
		month: 'short',
		day: 'numeric',
		hour: 'numeric',
		minute: '2-digit'
	});
}
