// The map's 3D clouds (Layers → Show → 3D clouds): puffs of cloud floating at their
// forecast heights around each location (./puffs.ts), drawn as soft camera-facing
// billboards in a MapLibre custom layer.
//
// The layer is "3d": it shares the depth buffer, so a ridge in front of a cloud hides it
// and a summit standing above a deck pokes through. Puffs are sorted far to near each
// time the map draws (a few hundred to a couple of thousand), blended without writing
// depth, and positioned relative to the map's centre so they hold still up close. Heights
// are scaled with the terrain's exaggeration, so a cloud based at 1,500 m meets the
// ground at 1,500 m. It is independent of the weather layers.
import type { CustomLayerInterface, CustomRenderMethodInput, Map as MlMap } from 'maplibre-gl';
import { sunPosition } from '../terrain/sun';
import { puffsAt, type CloudSite, type Puff } from './puffs';

/** Hidden zoomed out further than this (a location's clouds would be a few pixels). */
export const CLOUDS3D_MIN_ZOOM = 7.5;
/** Floats per puff in the instance buffer. */
const STRIDE = 8;

const VERT = `#version 300 es
in vec2 a_corner;        // -1..1 across the billboard
in vec3 a_pos;           // world pixels from the map's centre (x, y); metres up (z)
in vec4 a_look;          // half width (world px), height over width, darkness, solidity
in float a_seed;
uniform mat4 u_matrix;   // the map's matrix from the centre
uniform vec2 u_proj;     // the projection's x and y scale
uniform float u_pitch;   // 0 looking straight down, 1 at the horizon
out vec2 v_uv;
out float v_dark;
out float v_alpha;
out float v_seed;
void main() {
	vec4 c = u_matrix * vec4(a_pos, 1.0);
	// Thin layers look flat from the side, round from above.
	float squash = mix(1.0, a_look.y, u_pitch);
	// A puff that would fill much of the screen (the camera inside it) fades away.
	float size = a_look.x * u_proj.x / max(c.w, 1e-3);
	float near = 1.0 - smoothstep(0.3, 0.6, size);
	c.xy += a_corner * vec2(1.0, squash) * a_look.x * u_proj;
	gl_Position = c;
	v_uv = a_corner;
	v_dark = a_look.z;
	v_alpha = a_look.w * near;
	v_seed = a_seed;
}`;

const FRAG = `#version 300 es
precision highp float;
in vec2 v_uv;
in float v_dark;
in float v_alpha;
in float v_seed;
uniform float u_light;   // 1 by day, dimmer at night
uniform float u_warm;    // 0..1: the low sun's warm light
uniform float u_opacity;
out vec4 o_color;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
		mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
void main() {
	vec2 p = v_uv;
	// A lumpy edge: two octaves of noise, different for every puff.
	float n = noise(p * 2.2 + v_seed * 17.0) * 0.6 + noise(p * 4.7 + v_seed * 31.0) * 0.4;
	float d = length(p) + (n - 0.5) * 0.5;
	float a = smoothstep(1.0, 0.3, d) * v_alpha * u_opacity;
	if (a < 0.004) discard;
	// Lit from above: white tops, grey undersides, darker for a thick deck.
	float lit = clamp(0.5 + 0.5 * p.y + (n - 0.5) * 0.3, 0.0, 1.0);
	vec3 under = mix(vec3(0.80, 0.82, 0.86), vec3(0.48, 0.51, 0.57), v_dark);
	vec3 rgb = mix(under, vec3(1.0), lit) * u_light;
	rgb = mix(rgb, rgb * vec3(1.1, 0.9, 0.76), u_warm * lit);
	o_color = vec4(rgb * a, a);  // premultiplied, as the map blends
}`;

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
	const s = gl.createShader(type)!;
	gl.shaderSource(s, source);
	gl.compileShader(s);
	if (!gl.getShaderParameter(s, gl.COMPILE_STATUS) && !gl.isContextLost()) {
		const log = gl.getShaderInfoLog(s);
		gl.deleteShader(s);
		throw new Error(`3D clouds shader: ${log}`);
	}
	return s;
}

const smoothstep = (a: number, b: number, x: number) => {
	const u = Math.min(1, Math.max(0, (x - a) / (b - a)));
	return u * u * (3 - 2 * u);
};

/** Day and dusk light for a sun altitude (degrees): brightness and warmth. */
export function daylight(altitude: number): { light: number; warm: number } {
	const light = 0.38 + 0.62 * smoothstep(-8, 4, altitude);
	const warm = smoothstep(-6, 1, altitude) * (1 - smoothstep(4, 14, altitude));
	return { light, warm };
}

/** The puffs to draw, far to near, as instance data for a view: positions from the
 *  centre (world px, metres × exaggeration), each one's size in world px. Behind the
 *  camera or well off screen: left out. */
export function instances(
	puffs: Puff[],
	m: ArrayLike<number>,
	view: { cx: number; cy: number; worldSize: number; exaggeration: number; fade: number }
): { data: Float32Array; count: number } {
	const { cx, cy, worldSize: ws, exaggeration: ex, fade } = view;
	const keep: { w: number; i: number }[] = [];
	const pos = new Float64Array(puffs.length * 4);
	puffs.forEach((p, i) => {
		const x = p.x * ws - cx;
		const y = p.y * ws - cy;
		const z = p.z * ex;
		const r = p.r * p.per * ws;
		const w = m[3] * x + m[7] * y + m[11] * z + m[15];
		if (w <= 1e-6) return;
		const sx = (m[0] * x + m[4] * y + m[8] * z + m[12]) / w;
		const sy = (m[1] * x + m[5] * y + m[9] * z + m[13]) / w;
		const pad = 1.3 + (r * Math.abs(m[0])) / w;
		if (Math.abs(sx) > pad || Math.abs(sy) > pad + 0.4) return;
		pos.set([x, y, z, r], i * 4);
		keep.push({ w, i });
	});
	keep.sort((a, b) => b.w - a.w);
	const data = new Float32Array(keep.length * STRIDE);
	keep.forEach(({ i }, k) => {
		const p = puffs[i];
		data.set(
			[
				pos[i * 4],
				pos[i * 4 + 1],
				pos[i * 4 + 2],
				pos[i * 4 + 3],
				p.squash,
				p.dark,
				p.alpha * fade,
				p.seed
			],
			k * STRIDE
		);
	});
	return { data, count: keep.length };
}

interface Gfx {
	gl: WebGL2RenderingContext;
	program: WebGLProgram;
	vao: WebGLVertexArrayObject;
	corners: WebGLBuffer;
	inst: WebGLBuffer;
	loc: Record<string, WebGLUniformLocation | null>;
}

export class Clouds3dLayer {
	static readonly ID = 'clouds3d';
	readonly id = Clouds3dLayer.ID;
	private sites: CloudSite[] = [];
	private t = Date.now() / 1000;
	private puffs: Puff[] = [];
	private gfx: Gfx | null = null;
	private gone = false;
	private readonly layer: CustomLayerInterface;
	private onLost = () => (this.gfx = null);
	private onRestored = () => {
		this.attach();
		this.map.triggerRepaint();
	};

	constructor(private map: MlMap) {
		this.layer = {
			id: this.id,
			type: 'custom',
			renderingMode: '3d',
			render: (gl, args) => this.render(gl as WebGL2RenderingContext, args),
			onRemove: () => this.dispose()
		};
		this.attach();
		map.on('webglcontextlost', this.onLost);
		map.on('webglcontextrestored', this.onRestored);
	}

	private attach() {
		if (this.gone || this.map.getLayer(this.id)) return;
		try {
			// On top of the map's layers: cloud hides what's beneath it.
			this.map.addLayer(this.layer);
		} catch {
			this.map.once('style.load', () => this.attach());
		}
	}

	/** Every location's cloud layers. */
	setSites(sites: CloudSite[]) {
		this.sites = sites;
		this.update();
	}

	/** The time shown (Unix seconds): the weather slider's, or now. */
	setTime(t: number) {
		if (Math.abs(t - this.t) < 60) return;
		this.t = t;
		this.update();
	}

	/** How many puffs there are at the time shown (for tests and words). */
	get count(): number {
		return this.puffs.length;
	}

	private update() {
		this.puffs = puffsAt(this.sites, this.t);
		this.map.triggerRepaint();
	}

	private setup(gl: WebGL2RenderingContext): Gfx | null {
		try {
			const vs = compile(gl, gl.VERTEX_SHADER, VERT);
			const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
			const program = gl.createProgram()!;
			gl.attachShader(program, vs);
			gl.attachShader(program, fs);
			gl.bindAttribLocation(program, 0, 'a_corner');
			gl.bindAttribLocation(program, 1, 'a_pos');
			gl.bindAttribLocation(program, 2, 'a_look');
			gl.bindAttribLocation(program, 3, 'a_seed');
			gl.linkProgram(program);
			gl.deleteShader(vs);
			gl.deleteShader(fs);
			if (!gl.getProgramParameter(program, gl.LINK_STATUS) && !gl.isContextLost())
				throw new Error(`3D clouds program: ${gl.getProgramInfoLog(program)}`);
			const loc: Record<string, WebGLUniformLocation | null> = {};
			for (const n of ['u_matrix', 'u_proj', 'u_pitch', 'u_light', 'u_warm', 'u_opacity'])
				loc[n] = gl.getUniformLocation(program, n);
			const vao = gl.createVertexArray()!;
			const corners = gl.createBuffer()!;
			const inst = gl.createBuffer()!;
			gl.bindVertexArray(vao);
			gl.bindBuffer(gl.ARRAY_BUFFER, corners);
			gl.bufferData(
				gl.ARRAY_BUFFER,
				new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
				gl.STATIC_DRAW
			);
			gl.enableVertexAttribArray(0);
			gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
			gl.bindBuffer(gl.ARRAY_BUFFER, inst);
			const bytes = STRIDE * 4;
			gl.enableVertexAttribArray(1);
			gl.vertexAttribPointer(1, 3, gl.FLOAT, false, bytes, 0);
			gl.vertexAttribDivisor(1, 1);
			gl.enableVertexAttribArray(2);
			gl.vertexAttribPointer(2, 4, gl.FLOAT, false, bytes, 12);
			gl.vertexAttribDivisor(2, 1);
			gl.enableVertexAttribArray(3);
			gl.vertexAttribPointer(3, 1, gl.FLOAT, false, bytes, 28);
			gl.vertexAttribDivisor(3, 1);
			gl.bindVertexArray(null);
			gl.bindBuffer(gl.ARRAY_BUFFER, null);
			return { gl, program, vao, corners, inst, loc };
		} catch (e) {
			console.error(e);
			return null;
		}
	}

	private render(gl: WebGL2RenderingContext, args: CustomRenderMethodInput) {
		if (this.gone || !this.puffs.length) return;
		const map = this.map;
		const zoom = map.getZoom();
		const fade = smoothstep(CLOUDS3D_MIN_ZOOM, CLOUDS3D_MIN_ZOOM + 1, zoom);
		if (fade <= 0) return;
		if (this.gfx && this.gfx.gl.isContextLost()) this.gfx = null;
		this.gfx ??= this.setup(gl);
		const g = this.gfx;
		if (!g) return;
		const transform = (map as unknown as { transform?: { worldSize?: number } }).transform;
		const ws = transform?.worldSize ?? 512 * 2 ** zoom;
		const centre = map.getCenter();
		const cx = ((centre.lng + 180) / 360) * ws;
		const s = Math.sin((centre.lat * Math.PI) / 180);
		const cy = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * ws;
		// The map's matrix moved to the centre (in double precision, then to the chip).
		const mvp = args.modelViewProjectionMatrix as ArrayLike<number>;
		const m = new Float64Array(16);
		for (let i = 0; i < 16; i++) m[i] = mvp[i];
		for (let r = 0; r < 4; r++) m[12 + r] = mvp[r] * cx + mvp[4 + r] * cy + mvp[12 + r];
		const exaggeration = map.getTerrain()?.exaggeration ?? 1;
		const { data, count } = instances(this.puffs, m, {
			cx,
			cy,
			worldSize: ws,
			exaggeration,
			fade
		});
		if (!count) return;
		const p = args.projectionMatrix as ArrayLike<number>;
		const sun = sunPosition(this.t * 1000, centre.lat, centre.lng);
		const { light, warm } = daylight(sun.altitude);

		gl.useProgram(g.program);
		gl.bindVertexArray(g.vao);
		gl.bindBuffer(gl.ARRAY_BUFFER, g.inst);
		gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
		gl.uniformMatrix4fv(g.loc.u_matrix, false, new Float32Array(m));
		gl.uniform2f(g.loc.u_proj, Math.abs(p[0]), Math.abs(p[5]));
		gl.uniform1f(g.loc.u_pitch, Math.sin((map.getPitch() * Math.PI) / 180));
		gl.uniform1f(g.loc.u_light, light);
		gl.uniform1f(g.loc.u_warm, warm);
		gl.uniform1f(g.loc.u_opacity, 1);
		// Hidden by terrain in front, blended over one another far to near.
		gl.enable(gl.DEPTH_TEST);
		gl.depthFunc(gl.LEQUAL);
		gl.depthMask(false);
		gl.disable(gl.CULL_FACE);
		gl.enable(gl.BLEND);
		gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
		gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
		gl.depthMask(true);
		gl.bindVertexArray(null);
		gl.bindBuffer(gl.ARRAY_BUFFER, null);
	}

	private dispose() {
		const g = this.gfx;
		this.gfx = null;
		if (!g || g.gl.isContextLost()) return;
		g.gl.deleteProgram(g.program);
		g.gl.deleteVertexArray(g.vao);
		g.gl.deleteBuffer(g.corners);
		g.gl.deleteBuffer(g.inst);
	}

	remove() {
		this.gone = true;
		this.map.off('webglcontextlost', this.onLost);
		this.map.off('webglcontextrestored', this.onRestored);
		if (this.map.getLayer(this.id)) this.map.removeLayer(this.id);
		else this.dispose();
	}
}
