// The precipitation's shader: frames kept as numbers on the graphics chip, coloured at
// the screen's own resolution (docs/RADAR-PLAN.md, M2).
//
// One program draws everything, flat and draped on 3D terrain alike (./layer.ts gives it
// a different matrix, nothing else). For each screen pixel it reads the rate from the two
// frames either side of the time on the slider (each smoothed across its own pixels with
// a cubic B-spline: four bilinear reads), mixes them, and only then picks a colour, so an
// echo's outline is smooth and sharp at any zoom and frames run into one another.
//
// Lessons from the first attempt, reverted in b2d345a:
//   - data is uploaded from typed arrays, never through an image decoder (no
//     premultiplied alpha, no colour management);
//   - type is the share of snow and of mix, defined on every pixel wet or dry, so
//     interpolation never blends toward "no type";
//   - every texture can be dropped and rebuilt (a phone drops them in the background).
import type { Planes } from './codec';
import { ALPHA_FROM, buildLut, CODE_FROM, CODE_SOLID, LUT_ROWS, LUT_WIDTH } from './palette';

const VERT = `#version 300 es
in vec2 a_pos;          // 0..1 across the frames' box: x east, y south
uniform mat4 u_matrix;  // the box to clip space
out vec2 v_uv;
void main() {
	v_uv = a_pos;
	gl_Position = u_matrix * vec4(a_pos, 0.0, 1.0);
}`;

const FRAG = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform sampler2D u_rate_a;
uniform sampler2D u_rate_b;
uniform sampler2D u_type_a;
uniform sampler2D u_type_b;
uniform sampler2D u_lut;
uniform vec2 u_size_a;   // rate texture size, texels
uniform vec2 u_size_b;
uniform vec2 u_span_a;   // box uv to rate texture uv (a texture may overhang the box)
uniform vec2 u_span_b;
uniform vec2 u_tspan_a;  // box uv to type texture uv
uniform vec2 u_tspan_b;
uniform float u_mix;     // 0: frame a, 1: frame b
uniform float u_opacity;
uniform vec3 u_draw;     // code drawn from, code at full strength, strength at the first
out vec4 o_color;

// The rate code at uv, smoothed with a cubic B-spline over the 4x4 texels round it:
// four bilinear reads placed so the hardware's weights add up to the spline's.
float smoothCode(sampler2D tex, vec2 uv, vec2 size) {
	vec2 st = uv * size - 0.5;
	vec2 i = floor(st);
	vec2 f = st - i;
	vec2 f2 = f * f;
	vec2 f3 = f2 * f;
	vec2 w0 = (1.0 - 3.0 * f + 3.0 * f2 - f3) / 6.0;
	vec2 w1 = (4.0 - 6.0 * f2 + 3.0 * f3) / 6.0;
	vec2 w2 = (1.0 + 3.0 * f + 3.0 * f2 - 3.0 * f3) / 6.0;
	vec2 w3 = f3 / 6.0;
	vec2 g0 = w0 + w1;
	vec2 g1 = w2 + w3;
	vec2 p0 = (i - 0.5 + w1 / g0) / size;
	vec2 p1 = (i + 1.5 + w3 / g1) / size;
	float top = g0.x * texture(tex, vec2(p0.x, p0.y)).r + g1.x * texture(tex, vec2(p1.x, p0.y)).r;
	float bottom = g0.x * texture(tex, vec2(p0.x, p1.y)).r + g1.x * texture(tex, vec2(p1.x, p1.y)).r;
	return (g0.y * top + g1.y * bottom) * 255.0;
}

vec3 ramp(float code, float row) {
	return texture(u_lut, vec2((code + 0.5) / ${LUT_WIDTH}.0, (row + 0.5) / ${LUT_ROWS.length}.0)).rgb;
}

// 1 where d is clearly positive, 0 where clearly negative, a pixel-wide ramp between.
float side(float d) {
	float e = max(fwidth(d) * 0.75, 0.002);
	return smoothstep(-e, e, d);
}

void main() {
	float a = smoothCode(u_rate_a, v_uv * u_span_a, u_size_a);
	float b = smoothCode(u_rate_b, v_uv * u_span_b, u_size_b);
	float code = mix(a, b, u_mix);
	float e = max(fwidth(code) * 0.75, 0.05);
	float cover = smoothstep(u_draw.x - e, u_draw.x + e, code);
	if (cover <= 0.0) discard;
	float strength = mix(u_draw.z, 1.0, clamp((code - u_draw.x) / (u_draw.y - u_draw.x), 0.0, 1.0));

	// The type with the largest share of the water, the frame with more water counting
	// for more as one hands to the next.
	vec2 ta = texture(u_type_a, v_uv * u_tspan_a).rg;
	vec2 tb = texture(u_type_b, v_uv * u_tspan_b).rg;
	float wa = (1.0 - u_mix) * (a + 1.0);
	float wb = u_mix * (b + 1.0);
	vec2 t = (ta * wa + tb * wb) / (wa + wb);
	float snow = t.r;
	float mixed = t.g;
	float rain = max(0.0, 1.0 - snow - mixed);
	float ws = side(snow - max(mixed, rain));
	float wm = side(mixed - max(snow, rain));
	float wr = side(rain - max(snow, mixed));
	float sum = ws + wm + wr;
	vec3 rgb = sum > 0.0
		? (ws * ramp(code, 0.0) + wm * ramp(code, 1.0) + wr * ramp(code, 2.0)) / sum
		: ramp(code, 2.0);

	float alpha = cover * strength * u_opacity;
	o_color = vec4(rgb * alpha, alpha);  // premultiplied, as the map blends
}`;

/** A frame's two textures. */
export interface FrameTex {
	rate: WebGLTexture;
	type: WebGLTexture;
	width: number;
	height: number;
	typeWidth: number;
	typeHeight: number;
	ds: number;
	bytes: number;
}

const UNIFORMS = [
	'u_matrix',
	'u_rate_a',
	'u_rate_b',
	'u_type_a',
	'u_type_b',
	'u_lut',
	'u_size_a',
	'u_size_b',
	'u_span_a',
	'u_span_b',
	'u_tspan_a',
	'u_tspan_b',
	'u_mix',
	'u_opacity',
	'u_draw'
] as const;

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
	const s = gl.createShader(type)!;
	gl.shaderSource(s, source);
	gl.compileShader(s);
	if (!gl.getShaderParameter(s, gl.COMPILE_STATUS) && !gl.isContextLost()) {
		const log = gl.getShaderInfoLog(s);
		gl.deleteShader(s);
		throw new Error(`precipitation shader: ${log}`);
	}
	return s;
}

/**
 * The program, its quad and its colour table in one WebGL context. Everything here can be
 * thrown away and built again (`PrecipGl` is cheap to construct): after the context is
 * lost and restored the owner makes a new one and uploads its frames again.
 */
export class PrecipGl {
	private program: WebGLProgram;
	private loc = {} as Record<(typeof UNIFORMS)[number], WebGLUniformLocation | null>;
	private vao: WebGLVertexArrayObject;
	private quad: WebGLBuffer;
	private lut: WebGLTexture;

	constructor(
		readonly gl: WebGL2RenderingContext,
		/** The frames' box in the region's own pixels. */
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
			throw new Error(`precipitation program: ${gl.getProgramInfoLog(program)}`);
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

		this.lut = gl.createTexture()!;
		this.store();
		gl.bindTexture(gl.TEXTURE_2D, this.lut);
		gl.texImage2D(
			gl.TEXTURE_2D,
			0,
			gl.RGBA8,
			LUT_WIDTH,
			LUT_ROWS.length,
			0,
			gl.RGBA,
			gl.UNSIGNED_BYTE,
			buildLut()
		);
		// Along a ramp colours run smoothly; never between one type's row and the next.
		this.filter(gl.LINEAR);
		gl.bindTexture(gl.TEXTURE_2D, null);
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

	private filter(mode: number) {
		const gl = this.gl;
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mode);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, mode);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
	}

	/** A frame's planes as textures. */
	upload(p: Planes): FrameTex {
		const gl = this.gl;
		this.store();
		gl.activeTexture(gl.TEXTURE0);
		const rate = gl.createTexture()!;
		gl.bindTexture(gl.TEXTURE_2D, rate);
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, p.width, p.height, 0, gl.RED, gl.UNSIGNED_BYTE, p.rate);
		this.filter(gl.LINEAR);
		const type = gl.createTexture()!;
		gl.bindTexture(gl.TEXTURE_2D, type);
		gl.texImage2D(
			gl.TEXTURE_2D,
			0,
			gl.RG8,
			p.typeWidth,
			p.typeHeight,
			0,
			gl.RG,
			gl.UNSIGNED_BYTE,
			p.type
		);
		this.filter(gl.LINEAR);
		gl.bindTexture(gl.TEXTURE_2D, null);
		return {
			rate,
			type,
			width: p.width,
			height: p.height,
			typeWidth: p.typeWidth,
			typeHeight: p.typeHeight,
			ds: p.ds,
			bytes: p.rate.length + p.type.length
		};
	}

	free(t: FrameTex) {
		this.gl.deleteTexture(t.rate);
		this.gl.deleteTexture(t.type);
	}

	/** Our own objects still exist (a phone may drop them without a word). */
	alive(): boolean {
		return !this.gl.isContextLost() && this.gl.isTexture(this.lut);
	}

	/**
	 * Draw frames `a` and `b` mixed (`mix` 0: all `a`) with `matrix` taking the box (0..1,
	 * x east, y south) to clip space. Blending is left as the caller set it (premultiplied).
	 */
	draw(matrix: Float32Array | number[], a: FrameTex, b: FrameTex, mix: number, opacity: number) {
		const gl = this.gl;
		const u = this.loc;
		gl.useProgram(this.program);
		gl.bindVertexArray(this.vao);
		gl.uniformMatrix4fv(u.u_matrix, false, matrix);
		const bind = (unit: number, tex: WebGLTexture, loc: WebGLUniformLocation | null) => {
			gl.activeTexture(gl.TEXTURE0 + unit);
			gl.bindTexture(gl.TEXTURE_2D, tex);
			gl.uniform1i(loc, unit);
		};
		bind(0, a.rate, u.u_rate_a);
		bind(1, b.rate, u.u_rate_b);
		bind(2, a.type, u.u_type_a);
		bind(3, b.type, u.u_type_b);
		bind(4, this.lut, u.u_lut);
		const { boxWidth: W, boxHeight: H } = this;
		gl.uniform2f(u.u_size_a, a.width, a.height);
		gl.uniform2f(u.u_size_b, b.width, b.height);
		gl.uniform2f(u.u_span_a, W / (a.width * a.ds), H / (a.height * a.ds));
		gl.uniform2f(u.u_span_b, W / (b.width * b.ds), H / (b.height * b.ds));
		gl.uniform2f(u.u_tspan_a, W / (a.typeWidth * 4), H / (a.typeHeight * 4));
		gl.uniform2f(u.u_tspan_b, W / (b.typeWidth * 4), H / (b.typeHeight * 4));
		gl.uniform1f(u.u_mix, mix);
		gl.uniform1f(u.u_opacity, opacity);
		gl.uniform3f(u.u_draw, CODE_FROM, CODE_SOLID, ALPHA_FROM);
		gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
		gl.bindVertexArray(null);
		gl.activeTexture(gl.TEXTURE0);
	}

	dispose() {
		const gl = this.gl;
		gl.deleteProgram(this.program);
		gl.deleteVertexArray(this.vao);
		gl.deleteBuffer(this.quad);
		gl.deleteTexture(this.lut);
	}
}
