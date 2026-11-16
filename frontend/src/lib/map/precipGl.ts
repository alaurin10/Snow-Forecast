// Precipitation drawn by the GPU, in the map's own WebGL context (a MapLibre custom
// layer: ../precipOverlay.ts), at the screen's resolution.
//
// The server sends radar, nowcast and forecast frames as numbers: a grayscale PNG whose
// gray is an index meaning a type and a rate (backend/snowwatch/maps/palette.py, the
// index's `fine`). When a frame arrives, one pass at its own resolution turns each pixel
// into numbers the GPU can blend (rate and type shares). Then for each screen pixel, on
// every map frame, four blended reads give a cubic B-spline of those numbers (dry as 0),
// the type most present, and only then the colour: storms get smooth, sharp outlines and
// continuous colour at any zoom, for about the cost of an ordinary picture layer. Each
// frame is one upload and one small pass; pans, zooms and fades are cheap.
// The other weather layers' pictures (already coloured) are drawn as they are, smoothly.
// In 3D, `colorize` colours a frame on the CPU for a picture the map drapes.
import type { ExpressionSpecification } from 'maplibre-gl';
import type { PrecipKind, Ramp } from '../radar';

/** How fine frames' indices read (the index's `fine`, from palette.fine_spec). */
export interface FineSpec {
	/** The lightest rate drawn (mm of water an hour). */
	from: number;
	/** Fully opaque from this rate. */
	solid: number;
	ramps: { type: PrecipKind; start: number; steps: number; top: number }[];
}

const KINDS: PrecipKind[] = ['snow', 'mix', 'rain'];

/** The region's corners in mercator units (0–1, y down) give `v_uv` across the region. */
export const VERTEX = `#version 300 es
in vec2 a_pos;
uniform mat4 u_matrix;
uniform vec4 u_region;
out vec2 v_uv;
void main() {
	v_uv = (a_pos - u_region.xy) / (u_region.zw - u_region.xy);
	gl_Position = u_matrix * vec4(a_pos, 0.0, 1.0);
}`;

/** A full-texture quad, for preparing a frame at its own resolution. */
export const PREP_VERTEX = `#version 300 es
in vec2 a_pos;
out vec2 v_uv;
void main() {
	v_uv = vec2(a_pos.x, 1.0 - a_pos.y);
	gl_Position = vec4(a_pos * 2.0 - 1.0, 0.0, 1.0);
}`;

/**
 * Once per frame, at the frame's resolution: each pixel's index read as a rate and a type
 * (with the hand-over frame mixed in at its weight), written as numbers the GPU can blend
 * between pixels: r = √(rate / u_rtop), g, b, a = how much of it is snow, mix, rain.
 */
export const PREP_FRAGMENT = `#version 300 es
precision highp float;
precision highp int;
uniform sampler2D u_src;
uniform sampler2D u_under;
uniform highp sampler2D u_lut;
uniform vec2 u_size;
uniform float u_under_w;
uniform float u_rtop;
in vec2 v_uv;
out vec4 o;

void add(in sampler2D tex, ivec2 c, float w, inout float rate, inout vec3 kinds) {
	int idx = int(texelFetch(tex, c, 0).r * 255.0 + 0.5);
	vec2 kv = texelFetch(u_lut, ivec2(idx, 0), 0).rg;
	rate += w * kv.y;
	int k = int(kv.x + 0.5);
	if (k > 0) kinds[k - 1] += w;
}

void main() {
	ivec2 c = clamp(ivec2(v_uv * u_size), ivec2(0), ivec2(u_size) - 1);
	float rate = 0.0;
	vec3 kinds = vec3(0.0);
	add(u_src, c, 1.0 - u_under_w, rate, kinds);
	if (u_under_w > 0.0) add(u_under, c, u_under_w, rate, kinds);
	o = vec4(sqrt(min(rate, u_rtop) / u_rtop), kinds);
}`;

/**
 * Every map frame: the two prepared frames (the one fading in, `1`, over the one fading
 * out, `0`, at `u_t`). A fine frame is read with a cubic B-spline (four blended reads),
 * its rate and type shares smooth between pixels, and only then coloured, so outlines
 * are smooth and sharp at any zoom. A picture (mode 1) is drawn as it is. Out:
 * premultiplied colour, as MapLibre blends custom layers.
 */
export const FRAGMENT = `#version 300 es
precision highp float;
precision highp int;
uniform sampler2D u_tex0;
uniform sampler2D u_tex1;
uniform sampler2D u_ramp;
uniform vec2 u_size;
uniform ivec2 u_mode;
uniform float u_t;
uniform float u_opacity;
uniform float u_rtop;
uniform float u_lfrom;
uniform float u_lsolid;
uniform vec3 u_ltop;
in vec2 v_uv;
out vec4 o;

// A cubic B-spline from four bilinear reads (Sigg & Hadwiger, GPU Gems 2, ch. 20).
vec4 bspline(in sampler2D tex) {
	vec2 p = v_uv * u_size - 0.5;
	vec2 i = floor(p);
	vec2 f = p - i;
	vec2 f2 = f * f;
	vec2 f3 = f2 * f;
	vec2 w0 = (1.0 - 3.0 * f + 3.0 * f2 - f3) / 6.0;
	vec2 w1 = (4.0 - 6.0 * f2 + 3.0 * f3) / 6.0;
	vec2 w2 = (1.0 + 3.0 * f + 3.0 * f2 - 3.0 * f3) / 6.0;
	vec2 w3 = f3 / 6.0;
	vec2 g0 = w0 + w1;
	vec2 g1 = w2 + w3;
	vec2 h0 = (i - 0.5 + w1 / g0) / u_size;
	vec2 h1 = (i + 1.5 + w3 / g1) / u_size;
	vec4 a = texture(tex, vec2(h0.x, h0.y));
	vec4 b = texture(tex, vec2(h1.x, h0.y));
	vec4 c = texture(tex, vec2(h0.x, h1.y));
	vec4 d = texture(tex, vec2(h1.x, h1.y));
	return g0.y * (g0.x * a + g1.x * b) + g1.y * (g0.x * c + g1.x * d);
}

vec4 fine(in sampler2D tex) {
	vec4 v = bspline(tex);
	float rate = v.r * v.r * u_rtop;
	float lr = log(max(rate, 1e-6));
	// Sharp but not jagged: the outline fades over about a screen pixel.
	float fw = max(fwidth(lr), 1e-4);
	float edge = smoothstep(u_lfrom - fw, u_lfrom + fw, lr);
	if (edge <= 0.0) return vec4(0.0);
	vec3 kinds = v.gba;
	int k = kinds.x >= kinds.y && kinds.x >= kinds.z ? 0 : (kinds.y >= kinds.z ? 1 : 2);
	float top = k == 0 ? u_ltop.x : (k == 1 ? u_ltop.y : u_ltop.z);
	float t = clamp((lr - u_lfrom) / (top - u_lfrom), 0.0, 1.0);
	vec3 col = texture(u_ramp, vec2(t, (float(k) + 0.5) / 3.0)).rgb;
	float a = (0.55 + 0.45 * clamp((lr - u_lfrom) / (u_lsolid - u_lfrom), 0.0, 1.0)) * edge;
	return vec4(col * a, a);
}

vec4 frame(in sampler2D tex, int mode) {
	return mode == 0 ? fine(tex) : texture(tex, v_uv);
}

void main() {
	if (any(lessThan(v_uv, vec2(0.0))) || any(greaterThan(v_uv, vec2(1.0)))) discard;
	vec4 c = frame(u_tex1, u_mode.y);
	if (u_t < 1.0) c = mix(frame(u_tex0, u_mode.x), c, u_t);
	o = c * u_opacity;
}`;

/** The largest rate the prepared frames hold (mm/h): every ramp's top is under it. */
export const RATE_TOP = 64;

/** An opacity expression (['interpolate', ['linear'], ['zoom'], z, v, …], or a number) at
 *  a zoom: custom layers have no paint properties, so the layer works it out itself. */
export function opacityAt(expr: ExpressionSpecification | number, zoom: number): number {
	if (typeof expr === 'number') return expr;
	const stops = (expr as unknown[]).slice(3) as number[];
	if (expr[0] !== 'interpolate' || stops.length < 2) return 1;
	if (zoom <= stops[0]) return stops[1];
	for (let i = 2; i < stops.length; i += 2) {
		if (zoom <= stops[i]) {
			const f = (zoom - stops[i - 2]) / (stops[i] - stops[i - 2]);
			return stops[i - 1] + (stops[i + 1] - stops[i - 1]) * f;
		}
	}
	return stops[stops.length - 1];
}

// ---- Colours: each ramp's stops, run together in OKLab (as palette.py does) ------------

function hexRgb(h: string): [number, number, number] {
	return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}

const toLin = (v: number) => (v > 10 ? ((v / 255 + 0.055) / 1.055) ** 2.4 : v / 255 / 12.92);
const toSrgb = (v: number) => (v > 0.0031308 ? 1.055 * v ** (1 / 2.4) - 0.055 : 12.92 * v);

function oklab([r, g, b]: [number, number, number]): [number, number, number] {
	const [lr, lg, lb] = [toLin(r), toLin(g), toLin(b)];
	const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
	const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
	const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
	return [
		0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
		1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
		0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
	];
}

function fromOklab([L, A, B]: [number, number, number]): [number, number, number] {
	const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
	const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
	const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
	const lin = [
		4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
		-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
		-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s
	];
	return lin.map((v) => Math.round(toSrgb(Math.min(1, Math.max(0, v))) * 255)) as [
		number,
		number,
		number
	];
}

/** A ramp's colour at `rate`: smooth (in log rate, mixed in OKLab) from stop to stop. */
export function rampColor(ramp: Ramp, rate: number): [number, number, number] {
	const s = ramp.steps;
	if (rate <= s[0].from) return hexRgb(s[0].color);
	if (rate >= s[s.length - 1].from) return hexRgb(s[s.length - 1].color);
	for (let i = 0; i < s.length - 1; i++) {
		if (rate < s[i + 1].from) {
			const f = Math.log(rate / s[i].from) / Math.log(s[i + 1].from / s[i].from);
			const a = oklab(hexRgb(s[i].color));
			const b = oklab(hexRgb(s[i + 1].color));
			return fromOklab([
				a[0] + (b[0] - a[0]) * f,
				a[1] + (b[1] - a[1]) * f,
				a[2] + (b[2] - a[2]) * f
			]);
		}
	}
	return hexRgb(s[s.length - 1].color);
}

/** Index → (type 1–3, 0 for none; rate), as palette.FINE_KIND / FINE_VALUE. */
export function fineLut(spec: FineSpec): Float32Array {
	const out = new Float32Array(256 * 2);
	for (const r of spec.ramps) {
		const code = KINDS.indexOf(r.type) + 1;
		const step = (r.top / spec.from) ** (1 / r.steps);
		for (let i = 0; i < r.steps && r.start + i < 256; i++) {
			out[(r.start + i) * 2] = code;
			out[(r.start + i) * 2 + 1] = spec.from * step ** (i + 0.5);
		}
	}
	return out;
}

/** Each type's colours along its rates (log, from `from` to its top), a row each. */
export function rampTexels(
	spec: FineSpec,
	ramps: Record<PrecipKind, Ramp>,
	width = 256
): Uint8Array {
	const out = new Uint8Array(width * 3 * 4);
	KINDS.forEach((kind, row) => {
		const top = spec.ramps.find((r) => r.type === kind)?.top ?? 10;
		for (let x = 0; x < width; x++) {
			const rate = spec.from * (top / spec.from) ** (x / (width - 1));
			const [r, g, b] = rampColor(ramps[kind], rate);
			out.set([r, g, b, 255], (row * width + x) * 4);
		}
	});
	return out;
}

/**
 * A fine frame coloured on the CPU, pixel by pixel (for 3D, where the map drapes ordinary
 * pictures): `px` holds the decoded frame (RGBA, gray = index) and becomes the colours,
 * with `under` (another decoded frame) mixed in as numbers at its weight. Each pixel's
 * colour is the ramp's at its rate: smooth steps, which the map blends between pixels.
 */
export function colorize(
	px: Uint8ClampedArray,
	spec: FineSpec,
	ramps: Record<PrecipKind, Ramp>,
	under: Uint8ClampedArray | null = null,
	weight = 0
) {
	const lut = fineLut(spec);
	const tex = rampTexels(spec, ramps);
	const lfrom = Math.log(spec.from);
	const lsolid = Math.log(spec.solid);
	const ltop = KINDS.map((k) => Math.log(spec.ramps.find((r) => r.type === k)?.top ?? 10));
	// Index → colour, for frames without a hand-over (the usual case: a table lookup).
	const colour = (kind: number, rate: number, out: number) => {
		if (kind < 1 || !(rate >= spec.from)) {
			px[out + 3] = 0;
			return;
		}
		const lr = Math.log(rate);
		const k = kind - 1;
		const x = Math.round((255 * Math.min(1, (lr - lfrom) / (ltop[k] - lfrom))) as number);
		const at = (k * 256 + x) * 4;
		px[out] = tex[at];
		px[out + 1] = tex[at + 1];
		px[out + 2] = tex[at + 2];
		px[out + 3] = Math.round(255 * (0.55 + 0.45 * Math.min(1, (lr - lfrom) / (lsolid - lfrom))));
	};
	if (!under || weight <= 0) {
		const table = new Uint8ClampedArray(256 * 4);
		const keep = px;
		px = table;
		for (let i = 0; i < 256; i++) colour(lut[i * 2], lut[i * 2 + 1], i * 4);
		px = keep;
		const t32 = new Uint32Array(table.buffer);
		const p32 = new Uint32Array(px.buffer, px.byteOffset, px.length / 4);
		for (let i = 0; i < p32.length; i++) p32[i] = t32[px[i * 4]];
		return;
	}
	for (let o = 0; o < px.length; o += 4) {
		const a = px[o];
		const b = under[o];
		const ra = lut[a * 2 + 1] * (1 - weight);
		const rb = lut[b * 2 + 1] * weight;
		colour(ra >= rb ? lut[a * 2] : lut[b * 2], ra + rb, o);
	}
}
