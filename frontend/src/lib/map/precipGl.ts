// Precipitation coloured at the screen's resolution, on the GPU.
//
// The server sends radar, nowcast and forecast frames as numbers: a grayscale PNG whose
// gray is an index meaning a type and a rate (backend/snowwatch/maps/palette.py, the
// index's `fine`). Here a small WebGL program reads the frame around each screen pixel,
// smooths the rates (a cubic B-spline over 4×4 frame pixels, rates in mm/h, dry as 0),
// takes the type most present, and only then picks the colour. So a storm's outline is a
// smooth curve drawn sharp at any zoom, and the colour runs continuously inside, where a
// coloured picture stretched by the map shows blurred pixels.
//
// It draws one view-sized picture (the part of the frame on screen, a margin round it),
// which the map lays over the ground like any picture, draped in 3D too. A second frame
// can be mixed in (the hand-over from the nowcast), as numbers, at its weight.
import type { PrecipKind, Ramp } from '../radar';

/** How fine frames' indices read (the index's `fine`, from palette.fine_spec). */
export interface FineSpec {
	/** The lightest rate drawn (mm of water an hour), faintly. */
	from: number;
	/** Fully opaque from this rate. */
	solid: number;
	ramps: { type: PrecipKind; start: number; steps: number; top: number }[];
}

/** A rectangle of the frame, in frame pixels (x right, y down). */
export interface FrameRect {
	x0: number;
	y0: number;
	x1: number;
	y1: number;
}

const KINDS: PrecipKind[] = ['snow', 'mix', 'rain'];

const VERTEX = `#version 300 es
in vec2 a_pos;
out vec2 v_uv;
void main() {
	v_uv = a_pos * 0.5 + 0.5;
	gl_Position = vec4(a_pos, 0.0, 1.0);
}`;

const FRAGMENT = `#version 300 es
precision highp float;
precision highp int;
uniform sampler2D u_frame;
uniform sampler2D u_under;
uniform highp sampler2D u_lut;
uniform sampler2D u_ramp;
uniform vec4 u_rect;
uniform vec2 u_size;
uniform float u_under_w;
uniform float u_lfrom;
uniform float u_lsolid;
uniform vec3 u_ltop;
in vec2 v_uv;
out vec4 o;

// Cubic B-spline weights for the four pixels round a point (no overshoot, so rates never
// go below 0 or above their neighbours).
vec4 bspline(float t) {
	float t2 = t * t;
	float t3 = t2 * t;
	return vec4(
		(1.0 - t) * (1.0 - t) * (1.0 - t),
		3.0 * t3 - 6.0 * t2 + 4.0,
		-3.0 * t3 + 3.0 * t2 + 3.0 * t + 1.0,
		t3
	) / 6.0;
}

void gather(in sampler2D tex, ivec2 b, vec4 wx, vec4 wy, float share, inout float rate, inout vec3 kinds) {
	ivec2 hi = ivec2(u_size) - 1;
	for (int j = 0; j < 4; j++) {
		for (int i = 0; i < 4; i++) {
			ivec2 c = clamp(b + ivec2(i - 1, j - 1), ivec2(0), hi);
			int idx = int(texelFetch(tex, c, 0).r * 255.0 + 0.5);
			vec2 kv = texelFetch(u_lut, ivec2(idx, 0), 0).rg;
			float w = wx[i] * wy[j] * share;
			rate += w * kv.y;
			int k = int(kv.x + 0.5);
			if (k > 0) kinds[k - 1] += w;
		}
	}
}

void main() {
	vec2 p = vec2(mix(u_rect.x, u_rect.z, v_uv.x), mix(u_rect.w, u_rect.y, v_uv.y)) - 0.5;
	vec2 fl = floor(p);
	ivec2 b = ivec2(fl);
	vec4 wx = bspline(p.x - fl.x);
	vec4 wy = bspline(p.y - fl.y);
	float rate = 0.0;
	vec3 kinds = vec3(0.0);
	gather(u_frame, b, wx, wy, 1.0 - u_under_w, rate, kinds);
	if (u_under_w > 0.0) gather(u_under, b, wx, wy, u_under_w, rate, kinds);
	float lr = log(max(rate, 1e-6));
	// Sharp but not jagged: the outline fades over about a screen pixel.
	float fw = max(fwidth(lr), 1e-4);
	float edge = smoothstep(u_lfrom - fw, u_lfrom + fw, lr);
	if (edge <= 0.0) {
		o = vec4(0.0);
		return;
	}
	int k = kinds.x >= kinds.y && kinds.x >= kinds.z ? 0 : (kinds.y >= kinds.z ? 1 : 2);
	float top = k == 0 ? u_ltop.x : (k == 1 ? u_ltop.y : u_ltop.z);
	float t = clamp((lr - u_lfrom) / (top - u_lfrom), 0.0, 1.0);
	vec3 col = texture(u_ramp, vec2(t, (float(k) + 0.5) / 3.0)).rgb;
	float a = (0.25 + 0.75 * clamp((lr - u_lfrom) / (u_lsolid - u_lfrom), 0.0, 1.0)) * edge;
	o = vec4(col * a, a);
}`;

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

// ---- The renderer --------------------------------------------------------------------

export class PrecipGl {
	readonly canvas: HTMLCanvasElement;
	private gl: WebGL2RenderingContext;
	private prog: WebGLProgram;
	private tex: WebGLTexture[];
	/** Which frame each of the two frame textures holds. */
	private held: (string | null)[] = [null, null];
	private uni: Record<string, WebGLUniformLocation | null> = {};

	/** null where WebGL 2 isn't available (the map needs it, so rarely). */
	static create(spec: FineSpec, ramps: Record<PrecipKind, Ramp>, w: number, h: number) {
		try {
			const canvas = document.createElement('canvas');
			const gl = canvas.getContext('webgl2', {
				alpha: true,
				premultipliedAlpha: true,
				antialias: false,
				depth: false,
				stencil: false,
				preserveDrawingBuffer: false
			});
			return gl ? new PrecipGl(canvas, gl, spec, ramps, w, h) : null;
		} catch (e) {
			console.error('precipitation renderer', e);
			return null;
		}
	}

	private constructor(
		canvas: HTMLCanvasElement,
		gl: WebGL2RenderingContext,
		private spec: FineSpec,
		ramps: Record<PrecipKind, Ramp>,
		private w: number,
		private h: number
	) {
		this.canvas = canvas;
		this.gl = gl;
		const shader = (type: number, src: string) => {
			const s = gl.createShader(type)!;
			gl.shaderSource(s, src);
			gl.compileShader(s);
			if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
				throw new Error(gl.getShaderInfoLog(s) ?? '');
			return s;
		};
		const prog = gl.createProgram()!;
		gl.attachShader(prog, shader(gl.VERTEX_SHADER, VERTEX));
		gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FRAGMENT));
		gl.linkProgram(prog);
		if (!gl.getProgramParameter(prog, gl.LINK_STATUS))
			throw new Error(gl.getProgramInfoLog(prog) ?? '');
		this.prog = prog;
		gl.useProgram(prog);
		for (const name of [
			'u_frame',
			'u_under',
			'u_lut',
			'u_ramp',
			'u_rect',
			'u_size',
			'u_under_w',
			'u_lfrom',
			'u_lsolid',
			'u_ltop'
		])
			this.uni[name] = gl.getUniformLocation(prog, name);

		const buf = gl.createBuffer();
		gl.bindBuffer(gl.ARRAY_BUFFER, buf);
		gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
		const loc = gl.getAttribLocation(prog, 'a_pos');
		gl.enableVertexAttribArray(loc);
		gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

		const texture = (unit: number) => {
			const t = gl.createTexture()!;
			gl.activeTexture(gl.TEXTURE0 + unit);
			gl.bindTexture(gl.TEXTURE_2D, t);
			gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, unit === 3 ? gl.LINEAR : gl.NEAREST);
			gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, unit === 3 ? gl.LINEAR : gl.NEAREST);
			gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
			gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
			return t;
		};
		this.tex = [texture(0), texture(1)];
		// Empty until a frame arrives.
		for (const unit of [0, 1]) {
			gl.activeTexture(gl.TEXTURE0 + unit);
			gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, 1, 1, 0, gl.RED, gl.UNSIGNED_BYTE, new Uint8Array(1));
		}
		texture(2);
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.RG32F, 256, 1, 0, gl.RG, gl.FLOAT, fineLut(spec));
		texture(3);
		gl.texImage2D(
			gl.TEXTURE_2D,
			0,
			gl.RGBA8,
			256,
			3,
			0,
			gl.RGBA,
			gl.UNSIGNED_BYTE,
			rampTexels(spec, ramps)
		);
		gl.uniform1i(this.uni.u_frame, 0);
		gl.uniform1i(this.uni.u_under, 1);
		gl.uniform1i(this.uni.u_lut, 2);
		gl.uniform1i(this.uni.u_ramp, 3);
		gl.uniform2f(this.uni.u_size, w, h);
		const top = (kind: PrecipKind) => Math.log(spec.ramps.find((r) => r.type === kind)?.top ?? 10);
		gl.uniform1f(this.uni.u_lfrom, Math.log(spec.from));
		gl.uniform1f(this.uni.u_lsolid, Math.log(spec.solid));
		gl.uniform3f(this.uni.u_ltop, top('snow'), top('mix'), top('rain'));
		gl.disable(gl.BLEND);
	}

	/** Put a frame (its file, and its decoded picture) in texture 0 or 1, unless it's there. */
	hold(slot: 0 | 1, file: string, bmp: ImageBitmap) {
		if (this.held[slot] === file) return;
		const gl = this.gl;
		gl.activeTexture(gl.TEXTURE0 + slot);
		gl.bindTexture(gl.TEXTURE_2D, this.tex[slot]);
		gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
		gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
		gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, gl.RED, gl.UNSIGNED_BYTE, bmp);
		this.held[slot] = file;
	}

	holds(slot: 0 | 1) {
		return this.held[slot];
	}

	/** Draw `rect` of the held frame (with `underWeight` of texture 1 mixed in) into a
	 *  `width` × `height` picture on this.canvas. */
	render(rect: FrameRect, width: number, height: number, underWeight = 0) {
		const gl = this.gl;
		if (this.canvas.width !== width || this.canvas.height !== height) {
			this.canvas.width = width;
			this.canvas.height = height;
		}
		gl.viewport(0, 0, width, height);
		gl.useProgram(this.prog);
		gl.uniform4f(this.uni.u_rect, rect.x0, rect.y0, rect.x1, rect.y1);
		gl.uniform1f(this.uni.u_under_w, this.held[1] ? underWeight : 0);
		gl.clearColor(0, 0, 0, 0);
		gl.clear(gl.COLOR_BUFFER_BIT);
		gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
	}

	get frameSize() {
		return { w: this.w, h: this.h };
	}

	destroy() {
		const gl = this.gl;
		for (const t of this.tex) gl.deleteTexture(t);
		gl.deleteProgram(this.prog);
		gl.getExtension('WEBGL_lose_context')?.loseContext();
		this.canvas.width = this.canvas.height = 0;
	}
}
