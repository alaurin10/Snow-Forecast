// The snow total's shader: steps kept as numbers on the graphics chip (./steps.ts),
// coloured at the screen's own resolution, as the radar is (./gl.ts).
//
// For each pixel it reads the two steps either side of the time on the slider and mixes
// them (cm, so the total grows smoothly between steps). Zoomed out it shows the plain
// total (the models' own snow per cell); zoomed in, the snow at the pixel's own elevation
// from the step's bands, read from an elevation tile the terrain worker hands over (the
// tiles 3D and the hill shading use). Between the two zooms it fades from one to the other.
//
// One program draws everything, flat and draped on 3D terrain: a quad (the whole box, or
// one map tile) with a matrix to clip space and its place in the box.
import { TOTAL } from '../../radar';
import { CM_CODES, CM_MAX, CM_MIN, cmCode, codeCm } from './steps';
import type { StepPlanes } from './steps';

// The codes' scale as GLSL float literals.
const CM_MIN_GLSL = CM_MIN.toFixed(6);
const SPAN_GLSL = Math.log(CM_MAX / CM_MIN).toFixed(6);

const VERT = `#version 300 es
in vec2 a_pos;          // 0..1 across the quad: x east, y south
uniform mat4 u_matrix;  // the quad to clip space
uniform vec4 u_quad;    // the quad in the box's uv: x0, y0, width, height
uniform vec3 u_elevq;   // the quad in its elevation tile's uv: x0, y0, size
out vec2 v_box;
out vec2 v_elev;
void main() {
	v_box = u_quad.xy + a_pos * u_quad.zw;
	v_elev = u_elevq.xy + a_pos * u_elevq.z;
	gl_Position = u_matrix * vec4(a_pos, 0.0, 1.0);
}`;

const FRAG = `#version 300 es
precision highp float;
precision highp sampler3D;
in vec2 v_box;
in vec2 v_elev;
uniform sampler2D u_area_a;
uniform sampler2D u_area_b;
uniform sampler3D u_bands_a;
uniform sampler3D u_bands_b;
uniform sampler2D u_elev;
uniform sampler2D u_lut;
uniform vec2 u_aspan_a;   // box uv to area texture uv
uniform vec2 u_aspan_b;
uniform vec2 u_bspan_a;   // box uv to band texture uv
uniform vec2 u_bspan_b;
uniform vec2 u_bandk;     // bands in a and b (0: none)
uniform float u_band_m;   // metres between bands
uniform float u_mix;      // 0: step a, 1: step b
uniform float u_scale_a;  // step a's share of its own amount (0 for "nothing yet")
uniform float u_adjust;   // 0: the plain total, 1: the snow at each pixel's elevation
uniform float u_opacity;
uniform float u_first;    // the code where the colours start
out vec4 o_color;

float cm(float code) {
	return code >= 1.0 ? ${CM_MIN_GLSL} * exp((code - 1.0) / ${CM_CODES}.0 * ${SPAN_GLSL}) : 0.0;
}
float code(float c) {
	return c >= ${CM_MIN_GLSL}
		? min(${CM_CODES + 1}.0, 1.0 + ${CM_CODES}.0 * log(c / ${CM_MIN_GLSL}) / ${SPAN_GLSL})
		: 0.0;
}
// Elevation (m) at uv, bilinear between the tile's pixels: each pixel's channels carry one
// Terrarium number, so they are read one by one and the numbers blended.
float elevAt(ivec2 p, ivec2 size) {
	vec3 e = texelFetch(u_elev, clamp(p, ivec2(0), size - 1), 0).rgb * 255.0;
	return e.r * 256.0 + e.g + e.b / 256.0 - 32768.0;
}
float elevation(vec2 uv) {
	ivec2 size = textureSize(u_elev, 0);
	vec2 st = uv * vec2(size) - 0.5;
	ivec2 i = ivec2(floor(st));
	vec2 f = st - floor(st);
	float top = mix(elevAt(i, size), elevAt(i + ivec2(1, 0), size), f.x);
	float bottom = mix(elevAt(i + ivec2(0, 1), size), elevAt(i + ivec2(1, 1), size), f.x);
	return mix(top, bottom, f.y);
}
float band(sampler3D tex, vec2 uv, float k, float elev) {
	float w = clamp(elev / u_band_m, 0.0, k - 1.0);
	return cm(texture(tex, vec3(uv, (w + 0.5) / k)).r * 255.0);
}

void main() {
	if (any(lessThan(v_box, vec2(0.0))) || any(greaterThan(v_box, vec2(1.0)))) discard;
	float areaA = cm(texture(u_area_a, v_box * u_aspan_a).r * 255.0) * u_scale_a;
	float areaB = cm(texture(u_area_b, v_box * u_aspan_b).r * 255.0);
	float snow = mix(areaA, areaB, u_mix);
	if (u_adjust > 0.0) {
		float elev = elevation(v_elev);
		// A step without bands keeps its plain total.
		float a = u_bandk.x > 0.0 ? band(u_bands_a, v_box * u_bspan_a, u_bandk.x, elev) * u_scale_a : areaA;
		float b = u_bandk.y > 0.0 ? band(u_bands_b, v_box * u_bspan_b, u_bandk.y, elev) : areaB;
		snow = mix(snow, mix(a, b, u_mix), u_adjust);
	}
	float c = code(snow);
	float e = max(fwidth(c) * 0.75, 0.05);
	float alpha = smoothstep(u_first - e, u_first + e, c) * u_opacity;
	if (alpha <= 0.0) discard;
	vec3 rgb = texture(u_lut, vec2((max(c, u_first) + 0.5) / 256.0, 0.5)).rgb;
	o_color = vec4(rgb * alpha, alpha);  // premultiplied, as the map blends
}`;

/** Each code's colour on the snow total's steps (from TOTAL; nothing below the first). */
export function totalLut(): Uint8Array {
	const out = new Uint8Array(256 * 4);
	const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
	for (let c = 0; c < 256; c++) {
		const v = codeCm(c);
		let step = -1;
		for (let i = 0; i < TOTAL.length; i++) if (v >= TOTAL[i].from - 1e-6) step = i;
		const [r, g, b] = step < 0 ? [0, 0, 0] : hex(TOTAL[step].color);
		out.set([r, g, b, step < 0 ? 0 : 255], c * 4);
	}
	return out;
}

/** The code at which the first colour starts (1 inch). */
export const FIRST_CODE = cmCode(TOTAL[0].from);

/** A step's textures. */
export interface StepTex {
	area: WebGLTexture;
	bands: WebGLTexture;
	areaWidth: number;
	areaHeight: number;
	bandWidth: number;
	bandHeight: number;
	bandCount: number;
	bandM: number;
	bytes: number;
}

/** How a step is drawn this time. */
export interface Draw {
	/** The quad to clip space (column-major). */
	matrix: Float32Array | number[];
	/** The quad in the box's uv: x0, y0, width, height. */
	quad: [number, number, number, number];
	/** The quad in its elevation tile's uv (x0, y0, size), and the tile's texture; none:
	 *  the plain total only. */
	elev?: { tex: WebGLTexture; at: [number, number, number] };
	/** 0: the plain total, 1: the snow at each pixel's elevation. */
	adjust: number;
	opacity: number;
}

const UNIFORMS = [
	'u_matrix',
	'u_quad',
	'u_elevq',
	'u_area_a',
	'u_area_b',
	'u_bands_a',
	'u_bands_b',
	'u_elev',
	'u_lut',
	'u_aspan_a',
	'u_aspan_b',
	'u_bspan_a',
	'u_bspan_b',
	'u_bandk',
	'u_band_m',
	'u_mix',
	'u_scale_a',
	'u_adjust',
	'u_opacity',
	'u_first'
] as const;

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
	const s = gl.createShader(type)!;
	gl.shaderSource(s, source);
	gl.compileShader(s);
	if (!gl.getShaderParameter(s, gl.COMPILE_STATUS) && !gl.isContextLost()) {
		const log = gl.getShaderInfoLog(s);
		gl.deleteShader(s);
		throw new Error(`snow total shader: ${log}`);
	}
	return s;
}

/** The program, its quad, colour table and empty textures in one WebGL context; thrown
 *  away and built again after the context is lost (as PrecipGl). */
export class TotalGl {
	private program: WebGLProgram;
	private loc = {} as Record<(typeof UNIFORMS)[number], WebGLUniformLocation | null>;
	private vao: WebGLVertexArrayObject;
	private quad: WebGLBuffer;
	private lut: WebGLTexture;
	/** Stand-ins for a missing band set or elevation tile. */
	private none3d: WebGLTexture;
	private none2d: WebGLTexture;

	constructor(
		readonly gl: WebGL2RenderingContext,
		/** The steps' box in the region's own pixels. */
		private boxWidth: number,
		private boxHeight: number
	) {
		const vs = compile(gl, gl.VERTEX_SHADER, VERT);
		const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
		const program = gl.createProgram()!;
		gl.attachShader(program, vs);
		gl.attachShader(program, fs);
		gl.bindAttribLocation(program, 0, 'a_pos');
		gl.linkProgram(program);
		gl.deleteShader(vs);
		gl.deleteShader(fs);
		if (!gl.getProgramParameter(program, gl.LINK_STATUS) && !gl.isContextLost())
			throw new Error(`snow total program: ${gl.getProgramInfoLog(program)}`);
		this.program = program;
		for (const name of UNIFORMS) this.loc[name] = gl.getUniformLocation(program, name);

		this.vao = gl.createVertexArray()!;
		this.quad = gl.createBuffer()!;
		gl.bindVertexArray(this.vao);
		gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
		gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
		gl.enableVertexAttribArray(0);
		gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
		gl.bindVertexArray(null);
		gl.bindBuffer(gl.ARRAY_BUFFER, null);

		this.store();
		this.lut = this.tex2d(gl.RGBA8, 256, 1, gl.RGBA, totalLut(), gl.NEAREST);
		this.none2d = this.tex2d(gl.RGBA8, 1, 1, gl.RGBA, new Uint8Array([128, 0, 0, 255]), gl.NEAREST);
		this.none3d = gl.createTexture()!;
		gl.bindTexture(gl.TEXTURE_3D, this.none3d);
		gl.texImage3D(gl.TEXTURE_3D, 0, gl.R8, 1, 1, 1, 0, gl.RED, gl.UNSIGNED_BYTE, new Uint8Array(1));
		this.filter(gl.TEXTURE_3D, gl.NEAREST);
		gl.bindTexture(gl.TEXTURE_3D, null);
	}

	/** Bytes as they are: no flip, no premultiplying, rows of any length. */
	private store() {
		const gl = this.gl;
		gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
		gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
		gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
		gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
		gl.bindBuffer(gl.PIXEL_UNPACK_BUFFER, null);
	}

	private filter(target: number, mode: number) {
		const gl = this.gl;
		gl.texParameteri(target, gl.TEXTURE_MIN_FILTER, mode);
		gl.texParameteri(target, gl.TEXTURE_MAG_FILTER, mode);
		gl.texParameteri(target, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(target, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
		if (target === gl.TEXTURE_3D) gl.texParameteri(target, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
	}

	private tex2d(
		internal: number,
		w: number,
		h: number,
		format: number,
		data: Uint8Array,
		mode: number
	): WebGLTexture {
		const gl = this.gl;
		const t = gl.createTexture()!;
		gl.bindTexture(gl.TEXTURE_2D, t);
		gl.texImage2D(gl.TEXTURE_2D, 0, internal, w, h, 0, format, gl.UNSIGNED_BYTE, data);
		this.filter(gl.TEXTURE_2D, mode);
		gl.bindTexture(gl.TEXTURE_2D, null);
		return t;
	}

	/** A step's planes as textures. */
	upload(p: StepPlanes): StepTex {
		const gl = this.gl;
		this.store();
		gl.activeTexture(gl.TEXTURE0);
		const area = this.tex2d(gl.R8, p.areaWidth, p.areaHeight, gl.RED, p.area, gl.LINEAR);
		let bands = this.none3d;
		if (p.bandCount) {
			bands = gl.createTexture()!;
			gl.bindTexture(gl.TEXTURE_3D, bands);
			gl.texImage3D(
				gl.TEXTURE_3D,
				0,
				gl.R8,
				p.bandWidth,
				p.bandHeight,
				p.bandCount,
				0,
				gl.RED,
				gl.UNSIGNED_BYTE,
				p.bands
			);
			// Bilinear across the ground, linear between bands: the snow at any elevation.
			this.filter(gl.TEXTURE_3D, gl.LINEAR);
			gl.bindTexture(gl.TEXTURE_3D, null);
		}
		return {
			area,
			bands,
			areaWidth: p.areaWidth,
			areaHeight: p.areaHeight,
			bandWidth: p.bandWidth,
			bandHeight: p.bandHeight,
			bandCount: p.bandCount,
			bandM: p.bandM,
			bytes: p.area.length + p.bands.length
		};
	}

	/** An elevation tile (Terrarium RGBA, `size` px) as a texture: read pixel by pixel
	 *  (the channels carry one number, so they mustn't be blended). */
	elevation(rgba: Uint8Array, size: number): WebGLTexture {
		this.store();
		this.gl.activeTexture(this.gl.TEXTURE0);
		return this.tex2d(this.gl.RGBA8, size, size, this.gl.RGBA, rgba, this.gl.NEAREST);
	}

	free(t: StepTex) {
		this.gl.deleteTexture(t.area);
		if (t.bands !== this.none3d) this.gl.deleteTexture(t.bands);
	}

	freeTexture(t: WebGLTexture) {
		this.gl.deleteTexture(t);
	}

	alive(): boolean {
		return !this.gl.isContextLost() && this.gl.isTexture(this.lut);
	}

	/**
	 * Draw steps `a` and `b` mixed (`mix` 0: all `a`). `a` may be null: nothing yet (the
	 * slider before the first step). Blending is left as the caller set it.
	 */
	draw(a: StepTex | null, b: StepTex, mix: number, d: Draw) {
		const gl = this.gl;
		const u = this.loc;
		gl.useProgram(this.program);
		gl.bindVertexArray(this.vao);
		gl.uniformMatrix4fv(u.u_matrix, false, d.matrix);
		gl.uniform4f(u.u_quad, ...d.quad);
		gl.uniform3f(u.u_elevq, ...(d.elev?.at ?? [0, 0, 1]));
		const A = a ?? b;
		const bind = (
			unit: number,
			target: number,
			tex: WebGLTexture,
			loc: WebGLUniformLocation | null
		) => {
			gl.activeTexture(gl.TEXTURE0 + unit);
			gl.bindTexture(target, tex);
			gl.uniform1i(loc, unit);
		};
		bind(0, gl.TEXTURE_2D, A.area, u.u_area_a);
		bind(1, gl.TEXTURE_2D, b.area, u.u_area_b);
		bind(2, gl.TEXTURE_3D, A.bands, u.u_bands_a);
		bind(3, gl.TEXTURE_3D, b.bands, u.u_bands_b);
		bind(4, gl.TEXTURE_2D, d.elev?.tex ?? this.none2d, u.u_elev);
		bind(5, gl.TEXTURE_2D, this.lut, u.u_lut);
		const { boxWidth: W, boxHeight: H } = this;
		gl.uniform2f(u.u_aspan_a, W / (A.areaWidth * 2), H / (A.areaHeight * 2));
		gl.uniform2f(u.u_aspan_b, W / (b.areaWidth * 2), H / (b.areaHeight * 2));
		gl.uniform2f(u.u_bspan_a, W / Math.max(1, A.bandWidth * 4), H / Math.max(1, A.bandHeight * 4));
		gl.uniform2f(u.u_bspan_b, W / Math.max(1, b.bandWidth * 4), H / Math.max(1, b.bandHeight * 4));
		gl.uniform2f(u.u_bandk, A.bandCount, b.bandCount);
		gl.uniform1f(u.u_band_m, b.bandM || A.bandM || 500);
		gl.uniform1f(u.u_mix, mix);
		gl.uniform1f(u.u_scale_a, a ? 1 : 0);
		gl.uniform1f(u.u_adjust, d.elev ? d.adjust : 0);
		gl.uniform1f(u.u_opacity, d.opacity);
		gl.uniform1f(u.u_first, FIRST_CODE);
		gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
		gl.bindVertexArray(null);
		gl.activeTexture(gl.TEXTURE0);
	}

	dispose() {
		const gl = this.gl;
		gl.deleteProgram(this.program);
		gl.deleteVertexArray(this.vao);
		gl.deleteBuffer(this.quad);
		for (const t of [this.lut, this.none2d, this.none3d]) gl.deleteTexture(t);
	}
}
