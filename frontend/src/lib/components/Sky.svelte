<!-- The backdrop behind every page: the weather now at the open location (or the first
     location), at this moment of the day. A sky gradient whose colours follow the weather
     and the sun's height, the sun's halo along its arc (or the moon and stars at night),
     soft clouds that move with the wind, a ridgeline, and on a canvas whatever falls:
     rain, drizzle, snow, blowing snow, lightning. It changes with a slow crossfade.
     Fixed themes replace it with a still gradient. Motion "Subtle" keeps the clouds but
     drops what falls; "Off" (and the device's reduce-motion setting) stops everything.
     It also hands the glass a hint of the sky's colour (--sky-key). -->
<script lang="ts">
	import { prefs } from '../prefs.svelte';
	import { skyState } from '../skystate.svelte';
	import { colorMode } from '../mode.svelte';
	import { skyPaint } from '../skypaint';
	import SkyParticles from './SkyParticles.svelte';

	const sky = $derived(skyState.current);
	const dark = $derived(colorMode.dark);
	const paint = $derived(skyPaint(sky, dark));
	const live = $derived(prefs.themeFamily === 'sky');

	// The sun rises on the left and sets on the right, high at midday; after it sets, its
	// glow lingers at the edge it went down at. The moon crosses the night sky.
	const sunX = $derived(sky.night ? (sky.arc < 0.5 ? 94 : 6) : 8 + sky.arc * 84);
	const sunY = $derived(sky.night ? 50 : 44 - 52 * Math.sin(Math.PI * sky.arc));
	const moonX = $derived(10 + sky.arc * 80);
	const moonY = $derived(28 - 16 * Math.sin(Math.PI * sky.arc));
	// Clouds go by faster in wind.
	const cloudDur = $derived(Math.max(18, Math.min(70, 70 - sky.wind * 1.1)));

	// Deterministic "random" spread, so stars don't jump on every render.
	const rnd = (i: number, salt: number) => {
		const x = Math.sin(i * 127.1 + salt * 311.7) * 43758.5453;
		return x - Math.floor(x);
	};
	const stars = Array.from({ length: 46 }, (_, i) => ({
		left: `${(rnd(i, 11) * 100).toFixed(1)}%`,
		top: `${(rnd(i, 12) * 34).toFixed(1)}%`,
		size: `${(1 + rnd(i, 13) * 1.5).toFixed(1)}px`,
		dur: `${(3 + rnd(i, 14) * 4).toFixed(1)}s`,
		delay: `-${(rnd(i, 15) * 4).toFixed(1)}s`
	}));

	// Nothing moves while the tab is in the background, or when asked not to.
	let hidden = $state(false);
	let reduced = $state(false);
	$effect(() => {
		const on = () => (hidden = document.hidden);
		document.addEventListener('visibilitychange', on);
		const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
		reduced = !!mq?.matches;
		const onMq = (e: MediaQueryListEvent) => (reduced = e.matches);
		mq?.addEventListener('change', onMq);
		return () => {
			document.removeEventListener('visibilitychange', on);
			mq?.removeEventListener('change', onMq);
		};
	});
	const falling = $derived(live && prefs.motion === 'full' && !reduced && !hidden);

	// The glass takes a hint of the sky's colour (theme.css; Live Sky only).
	$effect(() => {
		const root = document.documentElement;
		if (live) root.style.setProperty('--sky-key', paint.key);
		else root.style.removeProperty('--sky-key');
	});
</script>

<div
	class="sky"
	data-weather={sky.weather}
	data-phase={sky.phase}
	class:paused={hidden}
	aria-hidden="true"
	style:--k1={live ? paint.k1 : undefined}
	style:--k2={live ? paint.k2 : undefined}
	style:--k3={live ? paint.k3 : undefined}
	style:--cloud={paint.cloud}
	style:--cloud-o={paint.cloudO}
	style:--glow={paint.glow}
	style:--glow-o={paint.glowO.toFixed(3)}
	style:--star-o={paint.starO.toFixed(3)}
	style:--moon-o={paint.moonO.toFixed(3)}
	style:--ridge1={live ? paint.ridge1 : undefined}
	style:--ridge2={live ? paint.ridge2 : undefined}
	style:--sun-x="{sunX.toFixed(2)}vw"
	style:--sun-y="{sunY.toFixed(2)}vh"
	style:--moon-x="{moonX.toFixed(2)}vw"
	style:--moon-y="{moonY.toFixed(2)}vh"
	style:--cloud-dur="{cloudDur.toFixed(0)}s"
>
	<div class="layer l3"></div>
	<div class="layer l2"></div>
	<div class="layer l1"></div>
	<div class="weather">
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
		<div class="moon"></div>
		<div class="glow"></div>
		<div class="clouds">
			<span class="cl a"></span>
			<span class="cl b"></span>
			<span class="cl c"></span>
			<span class="cl d"></span>
		</div>
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
	{#if live}
		<SkyParticles weather={sky.weather} wind={sky.wind} wdir={sky.wdir} {dark} active={falling} />
	{/if}
</div>

<style>
	.sky {
		position: fixed;
		inset: 0;
		z-index: -1;
		overflow: hidden;
		pointer-events: none;
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
	/* The sun's halo, centred on the sun's place; it moves a minute at a time. */
	.glow {
		left: 0;
		top: 0;
		width: min(560px, 80vw);
		aspect-ratio: 1;
		border-radius: 50%;
		background: radial-gradient(closest-side, var(--glow), transparent);
		opacity: var(--glow-o);
		transform: translate(calc(var(--sun-x) - 50%), calc(var(--sun-y) - 50%));
		transition:
			opacity var(--fade),
			transform 2s ease;
	}
	.moon {
		left: 0;
		top: 0;
		width: 44px;
		height: 44px;
		border-radius: 50%;
		background: radial-gradient(circle at 38% 36%, #fffdf4 0%, #ece8d8 55%, #d6d2c2 100%);
		box-shadow:
			0 0 40px 12px rgba(255, 252, 235, 0.22),
			0 0 120px 40px rgba(200, 210, 255, 0.1);
		opacity: var(--moon-o);
		transform: translate(calc(var(--moon-x) - 50%), calc(var(--moon-y) - 50%));
		transition:
			opacity var(--fade),
			transform 2s ease;
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
		transition: background-color var(--fade);
		animation: drift var(--cloud-dur) ease-in-out infinite alternate;
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
		animation-duration: calc(var(--cloud-dur) * 1.33);
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
		animation-duration: calc(var(--cloud-dur) * 1.23);
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
	.sky.paused * {
		animation-play-state: paused !important;
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

	/* Fixed themes: a still gradient, no weather. */
	:global(:root[data-theme]) .sky .weather {
		display: none;
	}
	:global(:root[data-theme]) .sky {
		--ridge1: rgba(255, 255, 255, 0.45);
		--ridge2: rgba(255, 255, 255, 0.78);
	}
	:global(:root[data-theme][data-mode='dark']) .sky {
		--ridge1: rgba(52, 70, 108, 0.55);
		--ridge2: rgba(30, 44, 74, 0.75);
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
