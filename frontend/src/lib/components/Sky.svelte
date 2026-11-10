<!-- The backdrop behind every page: the weather now at the open location (or the first
     location), drawn as a sky gradient, sun or moon glow, a few soft clouds, a ridgeline
     and, when it is snowing, slow snow. It is fixed behind the page and changes only
     when the scene changes, with a slow crossfade. Fixed themes replace it with a still
     gradient. Motion "Subtle" and "Off" (and the device's reduce-motion setting) drop
     the falling snow. -->
<script lang="ts">
	import { prefs } from '../prefs.svelte';
	import { skyState } from '../skystate.svelte';

	const sky = $derived(skyState.current);
	const veil = $derived(sky.night && sky.scene !== 'night');

	// Deterministic "random" spread, so flakes don't jump on every render.
	const rnd = (i: number, salt: number) => {
		const x = Math.sin(i * 127.1 + salt * 311.7) * 43758.5453;
		return x - Math.floor(x);
	};
	const flakeCount = $derived(
		prefs.motion !== 'full'
			? 0
			: sky.scene === 'heavy'
				? 60
				: sky.scene === 'snow'
					? 32
					: sky.scene === 'mixed'
						? 18
						: 0
	);
	const flakes = $derived(
		Array.from({ length: flakeCount }, (_, i) => {
			const dur = (sky.scene === 'heavy' ? 14 : 22) + rnd(i, 1) * 10;
			return {
				left: `${(rnd(i, 2) * 110 - 5).toFixed(1)}%`,
				size: `${(2 + rnd(i, 3) * 3.5).toFixed(1)}px`,
				opacity: (0.5 + rnd(i, 4) * 0.45).toFixed(2),
				dur: `${dur.toFixed(1)}s`,
				delay: `-${(rnd(i, 5) * dur).toFixed(1)}s`,
				drift: sky.scene === 'heavy' ? '120px' : '40px'
			};
		})
	);
	const stars = Array.from({ length: 46 }, (_, i) => ({
		left: `${(rnd(i, 11) * 100).toFixed(1)}%`,
		top: `${(rnd(i, 12) * 34).toFixed(1)}%`,
		size: `${(1 + rnd(i, 13) * 1.5).toFixed(1)}px`,
		dur: `${(3 + rnd(i, 14) * 4).toFixed(1)}s`,
		delay: `-${(rnd(i, 15) * 4).toFixed(1)}s`
	}));

	// Nothing moves while the tab is in the background.
	let hidden = $state(false);
	$effect(() => {
		const on = () => (hidden = document.hidden);
		document.addEventListener('visibilitychange', on);
		return () => document.removeEventListener('visibilitychange', on);
	});
</script>

<div class="sky" data-scene={sky.scene} class:veil class:paused={hidden} aria-hidden="true">
	<div class="layer l3"></div>
	<div class="layer l2"></div>
	<div class="layer l1"></div>
	<div class="weather">
		<div class="glow"></div>
		<div class="stars">
			{#each stars as s, i (i)}<i
					style:left={s.left}
					style:top={s.top}
					style:width={s.size}
					style:height={s.size}
					style:animation-duration={s.dur}
					style:animation-delay={s.delay}
				></i>{/each}
		</div>
		<div class="clouds">
			<span class="cl a"></span>
			<span class="cl b"></span>
			<span class="cl c"></span>
			<span class="cl d"></span>
		</div>
		<div class="dusk"></div>
	</div>
	<svg class="ridge" viewBox="0 0 1440 320" preserveAspectRatio="none">
		<path
			class="r1"
			d="M0 210 L90 170 L170 195 L260 120 L330 160 L420 90 L500 150 L590 110 L680 175 L770 130 L850 60 L930 130 L1010 100 L1100 165 L1190 115 L1280 150 L1360 95 L1440 140 V320 H0Z"
		/>
		<path
			class="r2"
			d="M0 262 L120 215 L220 245 L340 180 L450 235 L560 200 L690 250 L800 190 L900 240 L1020 205 L1140 255 L1260 210 L1350 240 L1440 200 V320 H0Z"
		/>
	</svg>
	<div class="flakes">
		{#each flakes as f, i (i)}<i
				style:left={f.left}
				style:width={f.size}
				style:height={f.size}
				style:opacity={f.opacity}
				style:animation-duration={f.dur}
				style:animation-delay={f.delay}
				style:--drift={f.drift}
			></i>{/each}
	</div>
</div>

<style>
	.sky {
		position: fixed;
		inset: 0;
		z-index: -1;
		overflow: hidden;
		pointer-events: none;
		/* Partly cloudy, the default. */
		--k1: #62a8ea;
		--k2: #a6d0f4;
		--k3: #e6f1fa;
		--cloud-o: 0.6;
		--glow-o: 1;
		--star-o: 0;
		--glow: rgba(255, 248, 224, 0.95);
		--cloud: rgba(255, 255, 255, 0.9);
		--ridge1: rgba(255, 255, 255, 0.45);
		--ridge2: rgba(255, 255, 255, 0.78);
		--dusk: #3b3f8f;
		--fade: 900ms ease;
	}
	.layer {
		position: absolute;
		inset: 0;
		transition: background-color var(--fade);
	}
	.l3 {
		background-color: var(--k3);
	}
	.l2 {
		background-color: var(--k2);
		-webkit-mask-image: linear-gradient(to bottom, #000 0%, #000 26%, transparent 78%);
		mask-image: linear-gradient(to bottom, #000 0%, #000 26%, transparent 78%);
	}
	.l1 {
		background-color: var(--k1);
		-webkit-mask-image: linear-gradient(to bottom, #000 0%, transparent 52%);
		mask-image: linear-gradient(to bottom, #000 0%, transparent 52%);
	}
	.weather > * {
		position: absolute;
		transition: opacity var(--fade);
	}
	.glow {
		right: 12%;
		top: -12vh;
		width: min(560px, 80vw);
		aspect-ratio: 1;
		border-radius: 50%;
		background: radial-gradient(closest-side, var(--glow), transparent);
		opacity: var(--glow-o);
	}
	.stars {
		inset: 0;
		opacity: var(--star-o);
	}
	.stars i {
		position: absolute;
		border-radius: 50%;
		background: #ffffff;
		animation: twinkle ease-in-out infinite;
	}
	.clouds {
		inset: 0 0 45% 0;
		opacity: var(--cloud-o);
	}
	.cl {
		position: absolute;
		border-radius: 50%;
		background: var(--cloud);
		filter: blur(36px);
		animation: drift 60s ease-in-out infinite alternate;
	}
	.cl.a {
		left: -6%;
		top: 6%;
		width: 46%;
		height: 26%;
	}
	.cl.b {
		left: 34%;
		top: 20%;
		width: 40%;
		height: 20%;
		animation-duration: 80s;
	}
	.cl.c {
		left: 66%;
		top: 2%;
		width: 44%;
		height: 30%;
	}
	.cl.d {
		left: 12%;
		top: 40%;
		width: 52%;
		height: 22%;
		animation-duration: 74s;
	}
	.dusk {
		inset: 0;
		background: var(--dusk);
		opacity: 0;
	}
	.sky.veil .dusk {
		opacity: 0.4;
	}
	.ridge {
		position: absolute;
		left: 0;
		bottom: 0;
		width: 100%;
		height: 32vh;
	}
	.ridge path {
		transition: fill var(--fade);
	}
	.r1 {
		fill: var(--ridge1);
	}
	.r2 {
		fill: var(--ridge2);
	}
	.flakes {
		position: absolute;
		inset: 0;
	}
	.flakes i {
		position: absolute;
		top: -12px;
		border-radius: 50%;
		background: #ffffff;
		box-shadow: 0 0 4px rgba(255, 255, 255, 0.7);
		animation: fall linear infinite;
	}
	.sky.paused * {
		animation-play-state: paused !important;
	}
	@keyframes fall {
		to {
			transform: translate3d(var(--drift), 105vh, 0);
		}
	}
	@keyframes drift {
		from {
			transform: translate3d(-30px, 0, 0);
		}
		to {
			transform: translate3d(50px, 0, 0);
		}
	}
	@keyframes twinkle {
		0%,
		100% {
			opacity: 0.35;
		}
		50% {
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.flakes {
			display: none;
		}
	}

	/* Scenes, light. */
	.sky[data-scene='clear'] {
		--k1: #4f9fec;
		--k2: #93c8f6;
		--k3: #dff0fc;
		--cloud-o: 0;
	}
	.sky[data-scene='night'] {
		--k1: #7f88d8;
		--k2: #aeb0e6;
		--k3: #e6dcf0;
		--cloud-o: 0;
		--star-o: 1;
		--glow: rgba(255, 255, 255, 0.5);
	}
	.sky[data-scene='glow'] {
		--k1: #8aa4e6;
		--k2: #f1b9b5;
		--k3: #ffe3c4;
		--cloud-o: 0.25;
		--glow: rgba(255, 196, 160, 0.9);
	}
	.sky[data-scene='overcast'] {
		--k1: #9fb0c4;
		--k2: #c2cedb;
		--k3: #e6ebf1;
		--cloud-o: 0.9;
		--glow-o: 0;
		--cloud: rgba(240, 243, 248, 0.85);
	}
	.sky[data-scene='snow'] {
		--k1: #a9bcd6;
		--k2: #cbd8e8;
		--k3: #eef3f9;
		--cloud-o: 0.8;
		--glow-o: 0;
	}
	.sky[data-scene='heavy'] {
		--k1: #b9c6da;
		--k2: #d6dfeb;
		--k3: #f4f7fb;
		--cloud-o: 1;
		--glow-o: 0;
	}
	.sky[data-scene='mixed'] {
		--k1: #a3b3c9;
		--k2: #c4cddc;
		--k3: #e3e6ee;
		--cloud-o: 0.9;
		--glow-o: 0;
		--cloud: rgba(240, 243, 248, 0.85);
	}
	.sky[data-scene='rain'] {
		--k1: #8fa6b8;
		--k2: #b3c4d0;
		--k3: #dbe4ea;
		--cloud-o: 0.9;
		--glow-o: 0;
		--cloud: rgba(240, 243, 248, 0.85);
	}
	.sky[data-scene='fog'] {
		--k1: #c5cdd6;
		--k2: #dde2e8;
		--k3: #f1f3f5;
		--cloud-o: 1;
		--glow-o: 0;
	}

	/* Scenes, dark: deepened, never black. */
	:global(:root[data-mode='dark']) .sky {
		--k1: #1b4275;
		--k2: #2d5f97;
		--k3: #5584b3;
		--glow: rgba(255, 226, 170, 0.35);
		--cloud: rgba(170, 186, 216, 0.3);
		--ridge1: rgba(52, 70, 108, 0.55);
		--ridge2: rgba(30, 44, 74, 0.75);
		--dusk: #070b1c;
	}
	:global(:root[data-mode='dark']) .sky.veil .dusk {
		opacity: 0.5;
	}
	:global(:root[data-mode='dark']) .sky[data-scene='clear'] {
		--k1: #173f77;
		--k2: #27609f;
		--k3: #4a86bf;
	}
	:global(:root[data-mode='dark']) .sky[data-scene='night'] {
		--k1: #131a33;
		--k2: #1d2a4f;
		--k3: #34416e;
		--glow: rgba(255, 255, 255, 0.5);
	}
	:global(:root[data-mode='dark']) .sky[data-scene='glow'] {
		--k1: #232a52;
		--k2: #6d4468;
		--k3: #b9705c;
		--glow: rgba(255, 196, 160, 0.9);
	}
	:global(:root[data-mode='dark']) .sky[data-scene='overcast'] {
		--k1: #2a3446;
		--k2: #3a475c;
		--k3: #536178;
	}
	:global(:root[data-mode='dark']) .sky[data-scene='snow'] {
		--k1: #26324a;
		--k2: #394966;
		--k3: #566a8a;
	}
	:global(:root[data-mode='dark']) .sky[data-scene='heavy'] {
		--k1: #222c42;
		--k2: #34425e;
		--k3: #4d5f80;
	}
	:global(:root[data-mode='dark']) .sky[data-scene='mixed'] {
		--k1: #242f44;
		--k2: #36445c;
		--k3: #50607a;
	}
	:global(:root[data-mode='dark']) .sky[data-scene='rain'] {
		--k1: #1f2d3a;
		--k2: #2f4252;
		--k3: #4a6072;
	}
	:global(:root[data-mode='dark']) .sky[data-scene='fog'] {
		--k1: #2c3440;
		--k2: #3d4652;
		--k3: #59626f;
	}

	/* Fixed themes: a still gradient, no weather. */
	:global(:root[data-theme]) .sky .weather,
	:global(:root[data-theme]) .sky .flakes {
		display: none;
	}
	:global(:root[data-theme='alpenglow']) .sky {
		--k1: #e7c3da;
		--k2: #f5dccd;
		--k3: #fbf2e9;
	}
	:global(:root[data-theme='glacier']) .sky {
		--k1: #bcd9f3;
		--k2: #dcecf9;
		--k3: #f5fafe;
	}
	:global(:root[data-theme='larch']) .sky {
		--k1: #f0d596;
		--k2: #f6e8c8;
		--k3: #fbf6ea;
	}
	:global(:root[data-theme='granite']) .sky {
		--k1: #cfd5dc;
		--k2: #e4e8ec;
		--k3: #f5f6f8;
	}
	:global(:root[data-theme='alpenglow'][data-mode='dark']) .sky {
		--k1: #2b2548;
		--k2: #4a3157;
		--k3: #7a4a5c;
	}
	:global(:root[data-theme='glacier'][data-mode='dark']) .sky {
		--k1: #1a2a44;
		--k2: #23406a;
		--k3: #2f5a8a;
	}
	:global(:root[data-theme='larch'][data-mode='dark']) .sky {
		--k1: #2b2620;
		--k2: #3d3324;
		--k3: #5a4622;
	}
	:global(:root[data-theme='granite'][data-mode='dark']) .sky {
		--k1: #23272e;
		--k2: #2e333b;
		--k3: #3d434d;
	}
</style>
