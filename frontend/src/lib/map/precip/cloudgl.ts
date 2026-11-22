// The forecast clouds' shader: a frame's numbers (./clouds.ts) kept on the graphics chip
// and drawn at the screen's own resolution.
//
// It draws the total cover as the server's pictures do (from a light veil to thick grey
// cloud), a full deck as a full layer. Zoomed in, where the frame knows the cloud's top
// (NBM's layers, to 36 h), it holds each pixel's own elevation (from the elevation tiles 3D
// and the hill shading use) against that top: ground standing above it shows through, under
// only the cloud higher up, so summits poke out of a sea of cloud. Between the two zooms it
// fades from one to the other; without tops it keeps the cover.
//
// One program draws everything, flat and draped on 3D terrain: a quad (the whole box, or
// one map tile) with a matrix to clip space and its place in the box.
import { COVER_FULL, FEATHER_M, type CloudPlanes } from './clouds';

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
in vec2 v_box;
in vec2 v_elev;
uniform sampler2D u_shares;  // cover, known, low, above
uniform sampler2D u_heights; // base, top
uniform sampler2D u_elev;
uniform vec2 u_span;         // box uv to the planes' uv
uniform float u_step;        // metres per height code
uniform float u_tops;        // 1: the tops are known
uniform float u_adjust;      // 0: the cover, 1: the cloud against the terrain
uniform float u_opacity;
out vec4 o_color;

const float FULL = ${COVER_FULL}.0 / 255.0;
const float FEATHER = ${FEATHER_M}.0;

// The server's picture of a cover (0..1): clear to 5%, then a light veil to thick cloud.
vec4 coverColor(float c) {
	float f = clamp((c * 100.0 - 5.0) / 95.0, 0.0, 1.0);
	float a = f > 0.0 ? (0.3 + 0.62 * pow(f, 0.8)) * smoothstep(0.0, 0.05, f) : 0.0;
	vec3 rgb = vec3(238.0 - 96.0 * f, 241.0 - 90.0 * f, 245.0 - 78.0 * f) / 255.0;
	return vec4(rgb, a);
}
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

void main() {
	if (any(lessThan(v_box, vec2(0.0))) || any(greaterThan(v_box, vec2(1.0)))) discard;
	vec2 uv = v_box * u_span;
	vec4 s = texture(u_shares, uv);
	vec4 plain = coverColor(s.r / FULL);
	vec4 color = vec4(plain.rgb * plain.a, plain.a);
	float k = u_adjust * s.g;
	if (k > 0.0) {
		// Seen from above, cloud hides everything beneath its top: the frame's cover holds
		// over all ground below the low cloud's top. Ground standing above it (a summit over
		// a sea of cloud) shows through, under only the cloud higher up.
		float top = texture(u_heights, uv).g * 255.0 * u_step;
		float z = elevation(v_elev);
		float total = s.r / FULL;
		float above = min(s.a / FULL, total);
		float out_ = smoothstep(top - FEATHER, top + FEATHER, z);
		vec4 c = coverColor(mix(total, above, out_));
		color = mix(color, vec4(c.rgb * c.a, c.a), k);
	}
	color *= u_opacity;
	if (color.a <= 0.002) discard;
	o_color = color;  // premultiplied, as the map blends
}`;

/** A frame's textures. */
export interface CloudTex {
	shares: WebGLTexture;
	heights: WebGLTexture;
	width: number;
	height: number;
	ds: number;
	stepM: number;
	tops: boolean;
	hasHeights: boolean;
	bytes: number;
}

/** How a frame is drawn this time. */
export interface CloudDraw {
	/** The quad to clip space (column-major). */
	matrix: Float32Array | number[];
	/** The quad in the box's uv: x0, y0, width, height. */
	quad: [number, number, number, number];
	/** The quad in its elevation tile's uv (x0, y0, size), and the tile's texture; none:
	 *  the cover only. */
	elev?: { tex: WebGLTexture; at: [number, number, number] };
	/** 0: the cover, 1: the cloud against the terrain. */
	adjust: number;
	opacity: number;
}

const UNIFORMS = [
	'u_matrix',
	'u_quad',
	'u_elevq',
	'u_shares',
	'u_heights',
	'u_elev',
	'u_span',
	'u_step',
	'u_tops',
	'u_adjust',
	'u_opacity'
] as const;

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
	const s = gl.createShader(type)!;
	gl.shaderSource(s, source);
	gl.compileShader(s);
	if (!gl.getShaderParameter(s, gl.COMPILE_STATUS) && !gl.isContextLost()) {
		const log = gl.getShaderInfoLog(s);
		gl.deleteShader(s);
		throw new Error(`cloud shader: ${log}`);
	}
	return s;
}

/** The program, its quad and a stand-in elevation tile in one WebGL context; thrown away
 *  and built again after the context is lost (as TotalGl). */
export class CloudGl {
	private program: WebGLProgram;
	private loc = {} as Record<(typeof UNIFORMS)[number], WebGLUniformLocation | null>;
	private vao: WebGLVertexArrayObject;
	private quad: WebGLBuffer;
	private none2d: WebGLTexture;

	constructor(
		readonly gl: WebGL2RenderingContext,
		/** The box in the region's own pixels. */
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
			throw new Error(`cloud program: ${gl.getProgramInfoLog(program)}`);
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
		this.none2d = this.tex2d(gl.RGBA8, 1, 1, gl.RGBA, new Uint8Array([128, 0, 0, 255]), gl.NEAREST);
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
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mode);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, mode);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
		gl.bindTexture(gl.TEXTURE_2D, null);
		return t;
	}

	/** A frame's planes as textures (bilinear: the cloud's edges and heights blend). */
	upload(p: CloudPlanes): CloudTex {
		const gl = this.gl;
		this.store();
		gl.activeTexture(gl.TEXTURE0);
		const shares = this.tex2d(gl.RGBA8, p.width, p.height, gl.RGBA, p.shares, gl.LINEAR);
		const heights = this.tex2d(gl.RG8, p.width, p.height, gl.RG, p.heights, gl.LINEAR);
		return {
			shares,
			heights,
			width: p.width,
			height: p.height,
			ds: p.ds,
			stepM: p.stepM,
			tops: (p.flags & 2) !== 0,
			hasHeights: (p.flags & 1) !== 0,
			bytes: p.shares.length + p.heights.length
		};
	}

	/** An elevation tile (Terrarium RGBA, `size` px) as a texture, read pixel by pixel. */
	elevation(rgba: Uint8Array, size: number): WebGLTexture {
		this.store();
		this.gl.activeTexture(this.gl.TEXTURE0);
		return this.tex2d(this.gl.RGBA8, size, size, this.gl.RGBA, rgba, this.gl.NEAREST);
	}

	free(t: CloudTex) {
		this.gl.deleteTexture(t.shares);
		this.gl.deleteTexture(t.heights);
	}

	freeTexture(t: WebGLTexture) {
		this.gl.deleteTexture(t);
	}

	alive(): boolean {
		return !this.gl.isContextLost() && this.gl.isTexture(this.none2d);
	}

	/** Draw a frame. Blending is left as the caller set it. */
	draw(t: CloudTex, d: CloudDraw) {
		const gl = this.gl;
		const u = this.loc;
		gl.useProgram(this.program);
		gl.bindVertexArray(this.vao);
		gl.uniformMatrix4fv(u.u_matrix, false, d.matrix);
		gl.uniform4f(u.u_quad, ...d.quad);
		gl.uniform3f(u.u_elevq, ...(d.elev?.at ?? [0, 0, 1]));
		const bind = (unit: number, tex: WebGLTexture, loc: WebGLUniformLocation | null) => {
			gl.activeTexture(gl.TEXTURE0 + unit);
			gl.bindTexture(gl.TEXTURE_2D, tex);
			gl.uniform1i(loc, unit);
		};
		bind(0, t.shares, u.u_shares);
		bind(1, t.heights, u.u_heights);
		bind(2, d.elev?.tex ?? this.none2d, u.u_elev);
		// The planes cover whole blocks of `ds` region pixels: a last part-block is left out.
		gl.uniform2f(u.u_span, this.boxWidth / (t.width * t.ds), this.boxHeight / (t.height * t.ds));
		gl.uniform1f(u.u_step, t.stepM);
		gl.uniform1f(u.u_tops, t.tops ? 1 : 0);
		gl.uniform1f(u.u_adjust, d.elev && t.hasHeights && t.tops ? d.adjust : 0);
		gl.uniform1f(u.u_opacity, d.opacity);
		gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
		gl.bindVertexArray(null);
		gl.activeTexture(gl.TEXTURE0);
	}

	dispose() {
		const gl = this.gl;
		gl.deleteProgram(this.program);
		gl.deleteVertexArray(this.vao);
		gl.deleteBuffer(this.quad);
		gl.deleteTexture(this.none2d);
	}
}
