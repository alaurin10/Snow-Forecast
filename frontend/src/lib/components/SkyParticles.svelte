<!-- What falls from the sky, drawn on one canvas: rain streaks slanted by the wind, drizzle,
     snow that drifts further the harder it blows, blowing snow racing sideways, and the
     odd lightning flash in a thunderstorm. Only drawn while `active` (Motion: Full, no
     reduce-motion, Live Sky); the browser stops the frames while the tab is hidden. -->
<script lang="ts">
	import type { Weather } from '../sky';

	let {
		weather,
		wind,
		wdir,
		dark,
		active
	}: {
		weather: Weather;
		wind: number;
		wdir: number | null;
		dark: boolean;
		active: boolean;
	} = $props();

	let canvas = $state<HTMLCanvasElement>();

	type Kind = 'rain' | 'drizzle' | 'snow' | 'blow';
	interface P {
		kind: Kind;
		x: number;
		y: number;
		vx: number;
		vy: number;
		/** Streak length (rain) or radius (snow). */
		size: number;
		alpha: number;
		/** Snow's sideways wobble. */
		phase: number;
		wob: number;
	}

	/** How many of each, for a 1440 × 900 window. */
	const MIX: Record<Weather, Partial<Record<Kind, number>>> = {
		clear: {},
		partly: {},
		overcast: {},
		fog: {},
		drizzle: { drizzle: 90 },
		rain: { rain: 160 },
		storm: { rain: 220 },
		mixed: { rain: 80, snow: 50 },
		snow: { snow: 70 },
		heavy: { snow: 170 },
		blowing: { blow: 150, snow: 40 }
	};

	const rand = (a: number, b: number) => a + Math.random() * (b - a);

	$effect(() => {
		const el = canvas;
		if (!el) return;
		const ctx = el.getContext('2d');
		if (!ctx) return;
		const mix = MIX[weather];
		const storm = weather === 'storm';
		if (!active || (!Object.keys(mix).length && !storm)) {
			ctx.clearRect(0, 0, el.width, el.height);
			return;
		}
		// Which way the wind carries things across the screen: from the west, to the right.
		const dir = wdir === null ? 1 : -Math.sin((wdir * Math.PI) / 180) || 1;
		const w = Math.min(Math.max(wind, 0), 90);
		const ink = dark ? '205, 218, 238' : '58, 78, 104';

		let W = 0;
		let H = 0;
		const resize = () => {
			const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
			W = window.innerWidth;
			H = window.innerHeight;
			el.width = Math.round(W * dpr);
			el.height = Math.round(H * dpr);
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		};
		resize();

		const spawn = (kind: Kind, anywhere: boolean): P => {
			const p: P = { kind, x: 0, y: 0, vx: 0, vy: 0, size: 0, alpha: 0, phase: 0, wob: 0 };
			if (kind === 'rain') {
				p.vy = rand(750, 1050);
				p.vx = dir * w * 6;
				p.size = rand(12, 22);
				p.alpha = rand(0.3, 0.55);
			} else if (kind === 'drizzle') {
				p.vy = rand(420, 560);
				p.vx = dir * w * 4;
				p.size = rand(5, 9);
				p.alpha = rand(0.25, 0.45);
			} else if (kind === 'snow') {
				p.vy = rand(35, 85);
				p.vx = dir * w * 3;
				p.size = rand(1, 3.2);
				p.alpha = rand(0.55, 0.95);
				p.phase = rand(0, Math.PI * 2);
				p.wob = rand(8, 26);
			} else {
				p.vy = rand(15, 60);
				p.vx = dir * Math.max(w, 30) * rand(7, 11);
				p.size = rand(0.8, 1.8);
				p.alpha = rand(0.45, 0.85);
			}
			// Start anywhere at first; afterwards, come in from the top or the upwind side.
			const slant = (p.vx / p.vy) * H;
			p.x = rand(Math.min(0, -slant), W + Math.max(0, -slant));
			p.y = anywhere ? rand(-20, H) : -20;
			if (!anywhere && kind === 'blow') {
				p.x = dir > 0 ? -20 : W + 20;
				p.y = rand(-20, H);
			}
			return p;
		};

		const scale = Math.min(1.3, Math.max(0.35, (W * H) / 1.3e6));
		const ps: P[] = [];
		for (const [kind, n] of Object.entries(mix) as [Kind, number][])
			for (let i = 0; i < Math.round(n * scale); i++) ps.push(spawn(kind, true));

		// Lightning: a bright flash and a weaker second one, every 4 to 14 s.
		let nextFlash = performance.now() + rand(2000, 8000);
		let flashAt = -1;

		let last = performance.now();
		let raf = 0;
		const frame = (now: number) => {
			const dt = Math.min(0.05, (now - last) / 1000);
			last = now;
			ctx.clearRect(0, 0, W, H);
			if (storm) {
				if (now >= nextFlash) {
					flashAt = now;
					nextFlash = now + rand(4000, 14000);
				}
				const s = now - flashAt;
				const a =
					flashAt < 0
						? 0
						: s < 120
							? 0.5 * (1 - s / 120)
							: s > 200 && s < 380
								? 0.3 * (1 - (s - 200) / 180)
								: 0;
				if (a > 0) {
					ctx.fillStyle = `rgba(255, 255, 255, ${a.toFixed(3)})`;
					ctx.fillRect(0, 0, W, H);
				}
			}
			ctx.lineCap = 'round';
			for (let i = 0; i < ps.length; i++) {
				const p = ps[i];
				p.y += p.vy * dt;
				p.x += p.vx * dt;
				if (p.kind === 'snow') p.phase += dt * 1.3;
				const x = p.kind === 'snow' ? p.x + Math.sin(p.phase) * p.wob : p.x;
				if (p.y > H + 24 || x < -60 || x > W + 60) {
					ps[i] = spawn(p.kind, false);
					continue;
				}
				if (p.kind === 'rain' || p.kind === 'drizzle' || p.kind === 'blow') {
					const len = p.kind === 'blow' ? Math.hypot(p.vx, p.vy) * 0.025 : p.size;
					const sp = Math.hypot(p.vx, p.vy) || 1;
					ctx.strokeStyle =
						p.kind === 'blow'
							? `rgba(255, 255, 255, ${p.alpha.toFixed(2)})`
							: `rgba(${ink}, ${p.alpha.toFixed(2)})`;
					ctx.lineWidth = p.kind === 'blow' ? p.size : p.kind === 'rain' ? 1.1 : 0.9;
					ctx.beginPath();
					ctx.moveTo(x, p.y);
					ctx.lineTo(x - (p.vx / sp) * len, p.y - (p.vy / sp) * len);
					ctx.stroke();
				} else {
					ctx.fillStyle = `rgba(255, 255, 255, ${p.alpha.toFixed(2)})`;
					ctx.beginPath();
					ctx.arc(x, p.y, p.size, 0, Math.PI * 2);
					ctx.fill();
				}
			}
			raf = requestAnimationFrame(frame);
		};
		raf = requestAnimationFrame(frame);
		window.addEventListener('resize', resize);
		return () => {
			cancelAnimationFrame(raf);
			window.removeEventListener('resize', resize);
			ctx.clearRect(0, 0, W, H);
		};
	});
</script>

<canvas class="particles" bind:this={canvas}></canvas>

<style>
	.particles {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
	}
</style>
