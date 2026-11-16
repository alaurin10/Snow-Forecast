// The precipitation pictures on the map.
//
// The server draws each frame as one picture over the locations' region (see
// ../radar.ts). Here we download them all once, keep them compressed (a couple of MB for
// the whole timeline), and decode only the frame on screen and its neighbours. Showing a
// frame is one texture upload into the map's own WebGL context (a custom layer): radar,
// nowcast and forecast frames carry numbers, smoothed and coloured on the GPU at the
// screen's resolution (map/precipGl.ts); the other layers' pictures are drawn as they are.
import type {
	CanvasSource,
	CustomLayerInterface,
	ExpressionSpecification,
	Map as MlMap
} from 'maplibre-gl';
import {
	colorize,
	fineLut,
	FRAGMENT,
	opacityAt,
	PREP_FRAGMENT,
	PREP_VERTEX,
	rampTexels,
	RATE_TOP,
	VERTEX,
	type FineSpec
} from './map/precipGl';
import { frameUrl, RAMPS } from './radar';

/** Anything with a picture file under /api/precip/: a frame or a snow total. */
type Pic = { file: string };

/** Decoded frames kept ready: the one on screen and a couple either side. */
const DECODED = 4;

export class FrameStore {
	private blobs = new Map<string, Blob>();
	private loading = new Map<string, Promise<Blob | null>>();
	private decoded = new Map<string, ImageBitmap>();
	/** Decodes under way, so two asks for one frame share one decode (and one bitmap). */
	private decoding = new Map<string, Promise<ImageBitmap | null>>();
	/** Cancels the downloads under way when the map closes. */
	private abort = new AbortController();
	private active = 0;
	private queue: (() => void)[] = [];

	has(f: Pic) {
		return this.blobs.has(f.file);
	}

	/** The frame's compressed picture, downloaded once (a few at a time). */
	blob(f: Pic, urgent = false): Promise<Blob | null> {
		const have = this.blobs.get(f.file);
		if (have) return Promise.resolve(have);
		let p = this.loading.get(f.file);
		if (!p) {
			p = this.limited(urgent, async () => {
				const res = await fetch(frameUrl(f), { signal: this.abort.signal });
				if (!res.ok) throw new Error(`frame ${res.status}`);
				return res.blob();
			}).then(
				(b) => {
					this.blobs.set(f.file, b);
					return b;
				},
				() => null
			);
			p.finally(() => this.loading.delete(f.file));
			this.loading.set(f.file, p);
		}
		return p;
	}

	/** The frame ready to draw. Older decoded frames are freed as new ones come in. */
	async bitmap(f: Pic): Promise<ImageBitmap | null> {
		const have = this.decoded.get(f.file);
		if (have) {
			this.decoded.delete(f.file);
			this.decoded.set(f.file, have);
			return have;
		}
		let p = this.decoding.get(f.file);
		if (!p) {
			p = this.decode(f).finally(() => this.decoding.delete(f.file));
			this.decoding.set(f.file, p);
		}
		return p;
	}

	private async decode(f: Pic): Promise<ImageBitmap | null> {
		const blob = await this.blob(f, true);
		if (!blob || !this.blobs.has(f.file)) return null;
		// No colour management: a fine frame's gray is a number, not a colour.
		const bmp = await createImageBitmap(blob, { colorSpaceConversion: 'none' });
		// Forgotten while it decoded (another timeline, or the map closed).
		if (!this.blobs.has(f.file)) {
			bmp.close();
			return null;
		}
		this.decoded.set(f.file, bmp);
		while (this.decoded.size > DECODED) {
			const [file, old] = this.decoded.entries().next().value!;
			this.decoded.delete(file);
			old.close();
		}
		return bmp;
	}

	/** Forget pictures no longer in the timeline. */
	keepOnly(frames: Pic[]) {
		const keep = new Set(frames.map((f) => f.file));
		for (const file of [...this.blobs.keys()]) if (!keep.has(file)) this.blobs.delete(file);
		for (const [file, bmp] of [...this.decoded]) {
			if (!keep.has(file)) {
				bmp.close();
				this.decoded.delete(file);
			}
		}
	}

	/** Forget everything and cancel the downloads under way (the map is closing). */
	clear() {
		this.abort.abort();
		this.abort = new AbortController();
		this.keepOnly([]);
	}

	/** At most four downloads at once; the frame being looked at jumps the queue. */
	private async limited<T>(urgent: boolean, job: () => Promise<T>): Promise<T> {
		if (this.active >= 4) {
			await new Promise<void>((r) => (urgent ? this.queue.unshift(r) : this.queue.push(r)));
		}
		this.active++;
		try {
			return await job();
		} finally {
			this.active--;
			this.queue.shift()?.();
		}
	}
}

/** A frame drawn over another, partly: the hand-over from the last nowcast frame to the
 *  forecast (radar.ts, `handover`). `weight` is the other frame's share. */
export interface Blend {
	file: string;
	bmp: ImageBitmap;
	weight: number;
}

/** What a picture is: numbers to colour (`fine`), or a picture to show as it is. */
export type PicKind = 'fine' | 'picture';

const mercY = (lat: number) =>
	0.5 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / (2 * Math.PI);
const mercX = (lon: number) => 0.5 + lon / 360;

/** One of the two frames the layer holds: the one on screen and the one fading out. */
interface Slot {
	file: string | null;
	kind: PicKind;
	/** The hand-over frame's share (fine frames). */
	underW: number;
}

/**
 * The precipitation (or another weather layer's picture) over the pictures' box.
 *
 * Flat, it's a MapLibre custom layer: a new frame is uploaded into the slot not on screen,
 * which then fades in over `fade` ms while the other fades out, all on the GPU. In 3D the
 * map drapes ordinary pictures over the terrain (a custom layer drawn into terrain tiles
 * keeps MapLibre redrawing them), so there each frame is coloured on the CPU into a canvas
 * source instead: the fine palette's steps, blended by the map, without fades.
 */
export class PrecipLayer {
	/** The flat layer's id (other layers are placed by it); IDS for code that handles each. */
	static readonly ID = 'precip';
	static readonly ID_3D = 'precip-3d';
	static readonly IDS = ['precip', 'precip-3d'] as const;
	private shown: string | null = null;
	private opacity: ExpressionSpecification | number;
	private slots: Slot[] = [
		{ file: null, kind: 'picture', underW: 0 },
		{ file: null, kind: 'picture', underW: 0 }
	];
	/** Which slot is on screen (fading in). */
	private front = 1;
	private fadeStart = 0;
	private fadeMs = 0;
	private fadeTimer = 0;
	/** Uploads waiting for the next draw (there's a GL context then). */
	private pending: { slot: number; bmp: ImageBitmap; kind: PicKind } | null = null;
	private pendingUnder: { file: string; bmp: ImageBitmap } | null = null;
	private underFile: string | null = null;
	private gl: WebGL2RenderingContext | null = null;
	private prog: WebGLProgram | null = null;
	private prep: WebGLProgram | null = null;
	private buf: WebGLBuffer | null = null;
	private quad: WebGLBuffer | null = null;
	/** The two slots' prepared frames (or pictures), and a framebuffer onto each. */
	private slotTex: WebGLTexture[] = [];
	private fbo: WebGLFramebuffer[] = [];
	/** The frame as decoded, the hand-over frame, the index lookup, the ramps. */
	private srcTex: WebGLTexture | null = null;
	private underTex: WebGLTexture | null = null;
	private lutTex: WebGLTexture | null = null;
	private rampTex: WebGLTexture | null = null;
	private uni: Record<string, WebGLUniformLocation | null> = {};
	private puni: Record<string, WebGLUniformLocation | null> = {};
	private region: [number, number, number, number];
	private bounds: [[number, number], [number, number]];
	private beforeId: string | undefined;
	/** The 3D picture (made the first time 3D is on), and the hand-over frame's pixels. */
	private canvas3d: HTMLCanvasElement | null = null;
	private under3d: { file: string; px: Uint8ClampedArray } | null = null;
	/** What's on screen, to show again when 3D goes on or off. */
	private last: {
		file: string | null;
		bmp: ImageBitmap | null;
		under: Blend | null;
		kind: PicKind;
	} = { file: null, bmp: null, under: null, kind: 'picture' };
	private onTerrain = () => this.switched();
	private layer: CustomLayerInterface & { terrainTileRevision: number };
	/** Milliseconds the last frame took to hand over and upload (perf.spec.ts, DevTools). */
	lastDrawMs = 0;

	constructor(
		private map: MlMap,
		bounds: [[number, number], [number, number]],
		private width: number,
		private height: number,
		opacity: unknown,
		beforeId?: string,
		private spec: FineSpec | null = null
	) {
		this.opacity = opacity as ExpressionSpecification;
		this.beforeId = beforeId;
		const [[south, west], [north, east]] = bounds;
		this.region = [mercX(west), mercY(north), mercX(east), mercY(south)];
		this.bounds = bounds;
		this.layer = {
			id: PrecipLayer.ID,
			type: 'custom',
			renderingMode: '2d',
			terrainTileRevision: 0,
			onAdd: (_map, gl) => this.setup(gl),
			onRemove: (_map, gl) => this.teardown(gl),
			render: (gl, args) => {
				// In 3D the canvas picture (draped) shows instead.
				if (this.map.getTerrain?.()) return;
				const m = args.defaultProjectionData.mainMatrix;
				this.paint(gl, m instanceof Float32Array ? m : new Float32Array(m));
			}
		};
		map.addLayer(this.layer, beforeId);
		map.on('terrain', this.onTerrain);
		if (map.getTerrain?.()) this.switched();
	}

	get showing() {
		return this.shown;
	}

	/** The pictures' opacity (by zoom). */
	setOpacity(opacity: unknown) {
		this.opacity = opacity as ExpressionSpecification;
		if (this.map.getLayer(PrecipLayer.ID_3D))
			this.map.setPaintProperty(PrecipLayer.ID_3D, 'raster-opacity', opacity as number);
		this.changed();
	}

	/** 3D went on or off: show the picture on screen the other way. */
	private switched() {
		const on = !!this.map.getTerrain?.();
		if (on) this.ensure3d();
		if (this.map.getLayer(PrecipLayer.ID_3D))
			this.map.setLayoutProperty(PrecipLayer.ID_3D, 'visibility', on ? 'visible' : 'none');
		const { file, bmp, under, kind } = this.last;
		if (bmp && !bmp.width) return; // freed: the next frame will show
		this.draw(file, bmp, 0, under, kind);
	}

	private ensure3d() {
		if (this.canvas3d) return;
		const canvas = document.createElement('canvas');
		canvas.width = this.width;
		canvas.height = this.height;
		this.canvas3d = canvas;
		const [[south, west], [north, east]] = this.bounds;
		this.map.addSource(PrecipLayer.ID_3D, {
			type: 'canvas',
			canvas,
			animate: false,
			coordinates: [
				[west, north],
				[east, north],
				[east, south],
				[west, south]
			]
		});
		this.map.addLayer(
			{
				id: PrecipLayer.ID_3D,
				type: 'raster',
				source: PrecipLayer.ID_3D,
				paint: {
					'raster-opacity': this.opacity as number,
					'raster-fade-duration': 0,
					'raster-resampling': 'linear'
				}
			},
			this.beforeId
		);
	}

	/** A frame into the 3D picture: a picture as it is, a fine frame coloured here. */
	private draw3d(bmp: ImageBitmap | null, under: Blend | null, kind: PicKind) {
		const canvas = this.canvas3d;
		if (!canvas) return;
		const t0 = performance.now();
		const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
		ctx.clearRect(0, 0, canvas.width, canvas.height);
		if (bmp && bmp.width) {
			ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
			if (kind === 'fine' && this.spec) {
				const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
				let underPx: Uint8ClampedArray | null = null;
				if (under && under.weight > 0) {
					if (this.under3d?.file !== under.file && under.bmp.width) {
						ctx.drawImage(under.bmp, 0, 0, canvas.width, canvas.height);
						this.under3d = {
							file: under.file,
							px: ctx.getImageData(0, 0, canvas.width, canvas.height).data
						};
					}
					underPx = this.under3d?.file === under.file ? this.under3d.px : null;
				}
				colorize(img.data, this.spec, RAMPS, underPx, under?.weight ?? 0);
				ctx.putImageData(img, 0, 0);
			}
		}
		const src = this.map.getSource(PrecipLayer.ID_3D) as CanvasSource | undefined;
		src?.play();
		src?.pause();
		const terrain = this.map.terrain;
		if (terrain) terrain.tileManager.releaseAllRTT();
		this.map.triggerRepaint();
		performance.measure?.('map:draw', { start: t0 });
	}

	/**
	 * Show a picture (null: nothing), fading from the one on screen over `fade` ms. A fine
	 * frame can have another mixed in under it (the hand-over), at that one's weight.
	 */
	draw(
		file: string | null,
		bmp: ImageBitmap | null,
		fade = 0,
		under: Blend | null = null,
		kind: PicKind = 'picture'
	) {
		const t0 = performance.now();
		this.last = { file, bmp, under, kind };
		this.shown = file;
		if (this.map.getTerrain?.()) {
			this.draw3d(bmp, under, kind);
			this.lastDrawMs = performance.now() - t0;
			return;
		}
		const back = 1 - this.front;
		const fine = kind === 'fine' && !!this.spec;
		this.slots[back] = {
			file: bmp ? file : null,
			kind: fine ? 'fine' : 'picture',
			underW: fine && under ? under.weight : 0
		};
		if (bmp) this.pending = { slot: back, bmp, kind: fine ? 'fine' : 'picture' };
		if (fine && under && under.file !== this.underFile)
			this.pendingUnder = { file: under.file, bmp: under.bmp };
		this.front = back;
		this.shown = file;
		this.fadeStart = performance.now();
		this.fadeMs = fade;
		this.animate();
		this.lastDrawMs = performance.now() - t0;
	}

	/** Repaint (and redrape in 3D) on every frame until the fade ends. */
	private animate() {
		globalThis.cancelAnimationFrame?.(this.fadeTimer);
		const step = () => {
			this.changed();
			if (performance.now() - this.fadeStart < this.fadeMs)
				this.fadeTimer = requestAnimationFrame(step);
		};
		step();
	}

	private changed() {
		this.layer.terrainTileRevision++;
		this.map.triggerRepaint();
	}

	private setup(gl: WebGL2RenderingContext) {
		this.gl = gl;
		const program = (vs: string, fs: string, names: string[]) => {
			const shader = (type: number, src: string) => {
				const sh = gl.createShader(type)!;
				gl.shaderSource(sh, src);
				gl.compileShader(sh);
				if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS))
					throw new Error(gl.getShaderInfoLog(sh) ?? 'shader');
				return sh;
			};
			const prog = gl.createProgram()!;
			gl.attachShader(prog, shader(gl.VERTEX_SHADER, vs));
			gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, fs));
			gl.linkProgram(prog);
			if (!gl.getProgramParameter(prog, gl.LINK_STATUS))
				throw new Error(gl.getProgramInfoLog(prog) ?? 'program');
			const uni: Record<string, WebGLUniformLocation | null> = {};
			for (const n of names) uni[n] = gl.getUniformLocation(prog, n);
			return { prog, uni };
		};
		const draw = program(VERTEX, FRAGMENT, [
			'u_matrix',
			'u_region',
			'u_tex0',
			'u_tex1',
			'u_ramp',
			'u_size',
			'u_mode',
			'u_t',
			'u_opacity',
			'u_rtop',
			'u_lfrom',
			'u_lsolid',
			'u_ltop'
		]);
		this.prog = draw.prog;
		this.uni = draw.uni;
		const prep = program(PREP_VERTEX, PREP_FRAGMENT, [
			'u_src',
			'u_under',
			'u_lut',
			'u_size',
			'u_under_w',
			'u_rtop'
		]);
		this.prep = prep.prog;
		this.puni = prep.uni;
		const [x0, y0, x1, y1] = this.region;
		this.buf = gl.createBuffer();
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
		gl.bufferData(
			gl.ARRAY_BUFFER,
			new Float32Array([x0, y0, x1, y0, x0, y1, x1, y1]),
			gl.STATIC_DRAW
		);
		this.quad = gl.createBuffer();
		gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
		gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
		const texture = (filter: number) => {
			const t = gl.createTexture()!;
			gl.bindTexture(gl.TEXTURE_2D, t);
			gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
			gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
			gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
			gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
			gl.texImage2D(
				gl.TEXTURE_2D,
				0,
				gl.RGBA8,
				1,
				1,
				0,
				gl.RGBA,
				gl.UNSIGNED_BYTE,
				new Uint8Array(4)
			);
			return t;
		};
		// Each slot: a frame-sized texture, blended between pixels, with a framebuffer.
		for (let i = 0; i < 2; i++) {
			const t = texture(gl.LINEAR);
			gl.texImage2D(
				gl.TEXTURE_2D,
				0,
				gl.RGBA8,
				this.width,
				this.height,
				0,
				gl.RGBA,
				gl.UNSIGNED_BYTE,
				null
			);
			const fb = gl.createFramebuffer()!;
			const was = gl.getParameter(gl.FRAMEBUFFER_BINDING);
			gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
			gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0);
			gl.bindFramebuffer(gl.FRAMEBUFFER, was);
			this.slotTex.push(t);
			this.fbo.push(fb);
		}
		this.srcTex = texture(gl.NEAREST);
		this.underTex = texture(gl.NEAREST);
		this.lutTex = texture(gl.NEAREST);
		this.rampTex = texture(gl.LINEAR);
		const spec = this.spec;
		if (spec) {
			gl.bindTexture(gl.TEXTURE_2D, this.lutTex);
			gl.texImage2D(gl.TEXTURE_2D, 0, gl.RG32F, 256, 1, 0, gl.RG, gl.FLOAT, fineLut(spec));
			gl.bindTexture(gl.TEXTURE_2D, this.rampTex);
			gl.texImage2D(
				gl.TEXTURE_2D,
				0,
				gl.RGBA8,
				256,
				3,
				0,
				gl.RGBA,
				gl.UNSIGNED_BYTE,
				rampTexels(spec, RAMPS)
			);
		}
	}

	private teardown(gl: WebGL2RenderingContext) {
		for (const t of [...this.slotTex, this.srcTex, this.underTex, this.lutTex, this.rampTex])
			if (t) gl.deleteTexture(t);
		for (const f of this.fbo) gl.deleteFramebuffer(f);
		for (const b of [this.buf, this.quad]) if (b) gl.deleteBuffer(b);
		for (const p of [this.prog, this.prep]) if (p) gl.deleteProgram(p);
		this.slotTex = [];
		this.fbo = [];
		this.prog = this.prep = null;
		this.gl = null;
	}

	/** A decoded picture into a texture as it is (the fast way). Pictures are premultiplied
	 *  and blended between pixels; a fine frame's numbers are read one by one. */
	private upload(gl: WebGL2RenderingContext, t: WebGLTexture, bmp: ImageBitmap, kind: PicKind) {
		gl.bindTexture(gl.TEXTURE_2D, t);
		gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
		gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, kind === 'picture');
		gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, bmp);
		gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
	}

	/** A new frame into its slot: a picture as it is; a fine frame's numbers read once, at
	 *  its own resolution, into rates and type shares the drawing can blend. */
	private prepare(gl: WebGL2RenderingContext) {
		const job = this.pending;
		this.pending = null;
		if (this.pendingUnder) {
			if (this.pendingUnder.bmp.width) {
				this.upload(gl, this.underTex!, this.pendingUnder.bmp, 'fine');
				this.underFile = this.pendingUnder.file;
			}
			this.pendingUnder = null;
		}
		if (!job || !job.bmp.width) return; // freed before it could be shown
		const t0 = performance.now();
		if (job.kind === 'picture') {
			this.upload(gl, this.slotTex[job.slot], job.bmp, 'picture');
		} else {
			this.upload(gl, this.srcTex!, job.bmp, 'fine');
			// Into the slot's framebuffer, then back to whatever the map was drawing into.
			const fb = gl.getParameter(gl.FRAMEBUFFER_BINDING);
			const vp = gl.getParameter(gl.VIEWPORT) as Int32Array;
			const blend = gl.isEnabled(gl.BLEND);
			gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo[job.slot]);
			gl.viewport(0, 0, this.width, this.height);
			gl.disable(gl.BLEND);
			gl.useProgram(this.prep);
			gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
			const loc = gl.getAttribLocation(this.prep!, 'a_pos');
			gl.enableVertexAttribArray(loc);
			gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
			const u = this.puni;
			const bind = (unit: number, tex: WebGLTexture, name: string) => {
				gl.activeTexture(gl.TEXTURE0 + unit);
				gl.bindTexture(gl.TEXTURE_2D, tex);
				gl.uniform1i(u[name], unit);
			};
			bind(0, this.srcTex!, 'u_src');
			bind(1, this.underTex!, 'u_under');
			bind(2, this.lutTex!, 'u_lut');
			gl.uniform2f(u.u_size, this.width, this.height);
			gl.uniform1f(u.u_under_w, this.underFile ? this.slots[job.slot].underW : 0);
			gl.uniform1f(u.u_rtop, RATE_TOP);
			gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
			gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
			gl.viewport(vp[0], vp[1], vp[2], vp[3]);
			if (blend) gl.enable(gl.BLEND);
		}
		// A frame's cost on the main thread: upload and preparation (e2e/perf.spec.ts).
		performance.measure?.('map:draw', { start: t0 });
	}

	private paint(gl: WebGL2RenderingContext, matrix: Float32Array) {
		if (!this.prog) return;
		if (this.pending || this.pendingUnder) this.prepare(gl);
		const t = this.fadeMs > 0 ? Math.min(1, (performance.now() - this.fadeStart) / this.fadeMs) : 1;
		const [b, f] = [this.slots[1 - this.front], this.slots[this.front]];
		if (!f.file && (t >= 1 || !b.file)) return;
		const opacity = opacityAt(this.opacity, this.map.getZoom());
		if (opacity <= 0) return;
		const u = this.uni;
		gl.useProgram(this.prog);
		gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
		const loc = gl.getAttribLocation(this.prog, 'a_pos');
		gl.enableVertexAttribArray(loc);
		gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
		gl.uniformMatrix4fv(u.u_matrix, false, matrix);
		gl.uniform4f(u.u_region, ...this.region);
		const bind = (unit: number, tex: WebGLTexture, name: string) => {
			gl.activeTexture(gl.TEXTURE0 + unit);
			gl.bindTexture(gl.TEXTURE_2D, tex);
			gl.uniform1i(u[name], unit);
		};
		const mode = (s: Slot) => (s.kind === 'fine' ? 0 : 1);
		// The slot fading out is "0", the one on screen "1"; an empty one on screen means
		// fading the old one out to clear.
		const outOnly = !f.file;
		bind(0, this.slotTex[1 - this.front], 'u_tex0');
		bind(1, this.slotTex[outOnly ? 1 - this.front : this.front], 'u_tex1');
		bind(2, this.rampTex!, 'u_ramp');
		gl.uniform2f(u.u_size, this.width, this.height);
		gl.uniform2i(u.u_mode, mode(b), mode(outOnly ? b : f));
		gl.uniform1f(u.u_t, !b.file || outOnly ? 1 : t);
		gl.uniform1f(u.u_opacity, outOnly ? opacity * (1 - t) : opacity);
		gl.uniform1f(u.u_rtop, RATE_TOP);
		if (this.spec) {
			const top = (k: string) => Math.log(this.spec!.ramps.find((r) => r.type === k)?.top ?? 10);
			gl.uniform1f(u.u_lfrom, Math.log(this.spec.from));
			gl.uniform1f(u.u_lsolid, Math.log(this.spec.solid));
			gl.uniform3f(u.u_ltop, top('snow'), top('mix'), top('rain'));
		}
		gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
	}

	remove() {
		globalThis.cancelAnimationFrame?.(this.fadeTimer);
		this.map.off('terrain', this.onTerrain);
		for (const id of PrecipLayer.IDS) if (this.map.getLayer(id)) this.map.removeLayer(id);
		if (this.map.getSource(PrecipLayer.ID_3D)) this.map.removeSource(PrecipLayer.ID_3D);
		if (this.canvas3d) this.canvas3d.width = this.canvas3d.height = 0;
		this.canvas3d = null;
		this.under3d = null;
	}
}
