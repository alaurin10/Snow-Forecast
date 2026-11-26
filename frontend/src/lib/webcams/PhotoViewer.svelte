<!--
  Field photos full screen. One at a time, the photo the focus, as large as the screen
  allows, with a short line under it: where, who, when, how far away, the photo's own
  caption, and a link to the full report (what the observer wrote is on the Backcountry
  tab). The text keeps well clear of the screen's rounded corners (the app doesn't extend
  under them, so safe-area insets are usually zero and fixed margins do the work).

  Moving: the arrow keys; the outer part of either side of the photo (a big target, with
  its arrow); or a swipe, the photo following the finger. Each new photo slides in
  quickly. Swipe down, Escape, ✕ or the phone's Back button close it. On wider screens a
  grid button shows every photo at once (`grid` opens it that way); a photo there opens on
  its own. Motion follows the app's setting: with motion off, photos just change.
-->
<script lang="ts">
	import { modal } from '../modal';
	import { safeHref, safeImage } from '../links';
	import type { UnitSystem } from '../units';
	import { reportFrom, reportWhen, type ViewerPhoto } from '../webcams';

	interface Props {
		photos: ViewerPhoto[];
		/** Which photo is showing; the viewer moves it. */
		index: number;
		units: UnitSystem;
		tz?: string | null;
		/** Start with every photo in a grid (wider screens). */
		grid?: boolean;
		onclose: () => void;
	}

	let { photos, index = $bindable(), units, tz = null, grid = false, onclose }: Props = $props();

	// svelte-ignore state_referenced_locally
	let mode = $state<'one' | 'grid'>(grid ? 'grid' : 'one');
	const count = $derived(photos.length);
	const at = $derived(Math.min(Math.max(index, 0), Math.max(count - 1, 0)));
	const cur = $derived(photos[at]);
	const away = (km: number) =>
		units === 'imperial' ? `${(km * 0.621371).toFixed(0)} mi` : `${km.toFixed(0)} km`;
	const meta = (p: ViewerPhoto) =>
		[reportFrom(p.report), reportWhen(p.report, tz), `${away(p.distance_km)} away`, p.report.region]
			.filter(Boolean)
			.join(' · ');

	// Which way the last move went, so the new photo slides in from that side.
	let dir = $state<'next' | 'prev' | null>(null);
	function go(step: number) {
		if (count < 2) return;
		dir = step > 0 ? 'next' : 'prev';
		index = (at + step + count) % count;
	}
	function show(i: number) {
		dir = null;
		index = i;
		mode = 'one';
	}

	// The photos either side load ahead, so flipping is quick.
	$effect(() => {
		for (const step of [1, -1]) {
			const next = photos[(at + step + count) % count];
			const src = next && safeImage(next.photo.url);
			if (src && count > 1) new Image().src = src;
		}
	});

	function onkey(e: KeyboardEvent) {
		if (mode !== 'one') return;
		if (e.key === 'ArrowRight') go(1);
		else if (e.key === 'ArrowLeft') go(-1);
		else return;
		e.preventDefault();
	}

	// Dragging: the photo follows the finger sideways (to flip) or down (to close).
	const AXIS_PX = 10; // movement before a drag picks its direction
	const FLIP_PX = 50;
	const CLOSE_PX = 100;
	let start: { x: number; y: number; t: number } | null = null;
	let axis = $state<'x' | 'y' | null>(null);
	let dx = $state(0);
	let dy = $state(0);
	// A swipe that ended over an arrow mustn't also count as a click on it.
	let swiped = false;

	function down(e: PointerEvent) {
		if (e.button !== 0) return;
		start = { x: e.clientX, y: e.clientY, t: performance.now() };
		axis = null;
		swiped = false;
	}
	function move(e: PointerEvent) {
		if (!start) return;
		const mx = e.clientX - start.x;
		const my = e.clientY - start.y;
		if (!axis) {
			if (Math.abs(mx) < AXIS_PX && Math.abs(my) < AXIS_PX) return;
			axis = Math.abs(mx) > Math.abs(my) ? 'x' : my > 0 ? 'y' : null;
			if (!axis) {
				start = null; // an upward drag: not ours
				return;
			}
			(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
		}
		if (axis === 'x') dx = count > 1 ? mx : mx / 4;
		else dy = Math.max(0, my);
	}
	function up() {
		if (!start) return;
		// The click that follows this pointer-up (if over an arrow) is the swipe's own.
		setTimeout(() => (swiped = false), 0);
		const fast = performance.now() - start.t < 250;
		if (axis === 'x') {
			swiped = true;
			if (count > 1 && (Math.abs(dx) >= FLIP_PX || (fast && Math.abs(dx) >= 25)))
				go(dx < 0 ? 1 : -1);
		} else if (axis === 'y') {
			swiped = true;
			if (dy >= CLOSE_PX || (fast && dy >= 40)) {
				start = null;
				onclose();
				return;
			}
		}
		start = null;
		axis = null;
		dx = 0;
		dy = 0;
	}
	function arrow(step: number) {
		if (swiped) {
			swiped = false;
			return;
		}
		go(step);
	}
	const dragging = $derived(axis !== null);
	const fade = $derived(Math.max(0.25, 1 - dy / 400));
</script>

<svelte:window onkeydown={onkey} />

<div class="modal" use:modal={{ onclose }}>
	<div
		class="viewer"
		class:grid-mode={mode === 'grid'}
		role="dialog"
		aria-modal="true"
		aria-label="Field photos"
		aria-roledescription="photo viewer"
		tabindex="-1"
		style:--fade={fade}
	>
		<header>
			<span class="count" aria-live="polite"
				>{mode === 'grid'
					? `${count} photo${count === 1 ? '' : 's'}`
					: `${at + 1} of ${count}`}</span
			>
			<span class="tools">
				{#if count > 1}
					<button
						type="button"
						class="round toggle"
						aria-pressed={mode === 'grid'}
						aria-label={mode === 'grid' ? 'One photo at a time' : 'All photos'}
						title={mode === 'grid' ? 'One at a time' : 'All photos'}
						onclick={() => (mode = mode === 'grid' ? 'one' : 'grid')}
					>
						{#if mode === 'grid'}
							<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
								><rect x="4" y="5" width="16" height="14" rx="2" fill="currentColor" /></svg
							>
						{:else}
							<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
								><path
									d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"
									fill="currentColor"
								/></svg
							>
						{/if}
					</button>
				{/if}
				<button type="button" class="round" onclick={onclose} aria-label="Close photos">✕</button>
			</span>
		</header>

		{#if mode === 'grid'}
			<ul class="gallery">
				{#each photos as p, i (i)}
					<li>
						<button type="button" onclick={() => show(i)} aria-label={`Open photo ${i + 1}`}>
							<img
								src={safeImage(p.photo.thumb)}
								alt={p.photo.caption || `Photo from “${p.report.title || 'a field report'}”`}
								loading="lazy"
								referrerpolicy="no-referrer"
							/>
							<span class="label"
								>{p.report.title || 'Field report'} · {reportWhen(p.report, tz)}</span
							>
						</button>
					</li>
				{/each}
			</ul>
		{:else}
			<div
				class="stage"
				role="presentation"
				onpointerdown={down}
				onpointermove={move}
				onpointerup={up}
				onpointercancel={up}
			>
				{#if cur && safeImage(cur.photo.url)}
					{#key at}
						<img
							class="photo"
							class:from-right={dir === 'next'}
							class:from-left={dir === 'prev'}
							class:settle={!dragging}
							src={safeImage(cur.photo.url)}
							alt={cur.photo.caption || `Photo from “${cur.report.title || 'a field report'}”`}
							referrerpolicy="no-referrer"
							draggable="false"
							style:transform={dragging ? `translate(${dx}px, ${dy}px)` : undefined}
							style:opacity={dy ? fade : undefined}
							style:background-image={safeImage(cur.photo.thumb)
								? `url("${safeImage(cur.photo.thumb)}")`
								: undefined}
						/>
					{/key}
				{/if}
				{#if count > 1}
					<button
						type="button"
						class="nav prev"
						onclick={() => arrow(-1)}
						aria-label="Previous photo"><span aria-hidden="true">‹</span></button
					>
					<button type="button" class="nav next" onclick={() => arrow(1)} aria-label="Next photo"
						><span aria-hidden="true">›</span></button
					>
				{/if}
			</div>
			{#if cur}
				<div class="foot" style:opacity={dy ? fade : undefined}>
					<div class="info">
						<p class="title">
							<strong>{cur.report.title || 'Field report'}</strong>
							{#if safeHref(cur.report.url)}
								<!-- External site: resolve() is only for routes in this app. -->
								<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
								<a href={safeHref(cur.report.url)} target="_blank" rel="noopener noreferrer"
									>Full report ↗</a
								>
							{/if}
						</p>
						<p class="meta">{meta(cur)}</p>
						{#if cur.photo.caption}<p class="caption">{cur.photo.caption}</p>{/if}
					</div>
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.modal {
		display: contents;
	}
	.viewer {
		position: fixed;
		inset: 0;
		z-index: 60;
		display: grid;
		grid-template-rows: auto minmax(0, 1fr) auto;
		/* Fades as the photo is pulled down to close. */
		background: rgb(6 9 15 / var(--fade, 1));
		color: #f3f5f8;
		outline: none;
	}
	.viewer.grid-mode {
		grid-template-rows: auto minmax(0, 1fr);
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		/* Clear of rounded corners: the count and buttons sit well in from the top corners. */
		padding: max(14px, calc(env(safe-area-inset-top) + 8px))
			max(20px, calc(env(safe-area-inset-right) + 12px)) 6px
			max(24px, calc(env(safe-area-inset-left) + 16px));
	}
	.count {
		font-size: 0.85rem;
		color: #c3cad6;
		font-variant-numeric: tabular-nums;
	}
	.tools {
		display: flex;
		gap: 8px;
	}
	.round {
		width: 44px;
		height: 44px;
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 50%;
		background: rgb(255 255 255 / 0.1);
		color: inherit;
		font-size: 1.1rem;
		cursor: pointer;
	}
	/* The grid is for wide screens; phones flip with a swipe. */
	.toggle {
		display: none;
	}
	@media (min-width: 720px) {
		.toggle {
			display: grid;
		}
	}
	.stage {
		position: relative;
		display: grid;
		place-items: center;
		min-height: 0;
		overflow: hidden;
		/* Sideways and downward drags are ours; pinching still zooms. */
		touch-action: pinch-zoom;
		user-select: none;
	}
	/* Fills the space between the bar and the caption, the photo scaled to fit inside it;
	   the small copy shows in the same place until the large one arrives. */
	.photo {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: contain;
		background-size: contain;
		background-repeat: no-repeat;
		background-position: center;
	}
	.photo.settle {
		transition:
			transform 160ms ease-out,
			opacity 160ms ease-out;
	}
	/* A quick slide in from the side it came from (motion off: none, by the theme). */
	.photo.from-right {
		animation: in-right 170ms ease-out;
	}
	.photo.from-left {
		animation: in-left 170ms ease-out;
	}
	@keyframes in-right {
		from {
			transform: translateX(14%);
			opacity: 0.35;
		}
	}
	@keyframes in-left {
		from {
			transform: translateX(-14%);
			opacity: 0.35;
		}
	}
	/* Previous / next: the outer part of each side, its arrow the visible part. */
	.nav {
		position: absolute;
		top: 0;
		bottom: 0;
		width: 30%;
		display: flex;
		align-items: center;
		padding: 0 8px;
		border: 0;
		background: none;
		color: #fff;
		cursor: pointer;
	}
	.prev {
		left: 0;
		justify-content: flex-start;
	}
	.next {
		right: 0;
		justify-content: flex-end;
	}
	.nav span {
		display: grid;
		place-items: center;
		width: 44px;
		height: 64px;
		border-radius: 10px;
		background: rgb(0 0 0 / 0.45);
		font-size: 2rem;
		line-height: 1;
		transition: background 120ms;
	}
	.nav:hover span,
	.round:hover {
		background: rgb(255 255 255 / 0.22);
	}
	.round:focus-visible,
	.nav:focus-visible span,
	.gallery button:focus-visible,
	.info a:focus-visible {
		outline: 2px solid #fff;
		outline-offset: 2px;
	}
	.nav:focus-visible {
		outline: none;
	}
	/* The margin sits outside the scrolling text, so no line ever scrolls into a corner. */
	.foot {
		padding: 10px max(24px, calc(env(safe-area-inset-right) + 16px))
			max(34px, calc(env(safe-area-inset-bottom) + 20px))
			max(24px, calc(env(safe-area-inset-left) + 16px));
		display: grid;
	}
	.info {
		display: grid;
		gap: 6px;
		align-content: start;
		max-height: 24vh;
		overflow-y: auto;
		overscroll-behavior: contain;
		max-width: 860px;
		width: 100%;
		justify-self: center;
		box-sizing: border-box;
	}
	.info p {
		margin: 0;
	}
	.title {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 2px 12px;
	}
	.title a {
		color: #9cc6ff;
		font-size: 0.9rem;
		white-space: nowrap;
	}
	.meta {
		font-size: 0.82rem;
		color: #c3cad6;
	}
	.caption {
		font-size: 0.92rem;
		line-height: 1.4;
	}
	/* Every photo at once: as many columns as fit, each photo big enough to judge. */
	.gallery {
		list-style: none;
		margin: 0;
		padding: 4px max(24px, calc(env(safe-area-inset-right) + 16px)) 32px
			max(24px, calc(env(safe-area-inset-left) + 16px));
		overflow-y: auto;
		display: grid;
		gap: 12px;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		align-content: start;
	}
	.gallery button {
		position: relative;
		display: block;
		width: 100%;
		padding: 0;
		border: 0;
		border-radius: 8px;
		overflow: hidden;
		background: #111826;
		cursor: zoom-in;
	}
	.gallery img {
		display: block;
		width: 100%;
		aspect-ratio: 4 / 3;
		object-fit: cover;
		transition: transform 160ms ease-out;
	}
	.gallery button:hover img {
		transform: scale(1.03);
	}
	.label {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		padding: 18px 10px 7px;
		background: linear-gradient(transparent, rgb(0 0 0 / 0.7));
		color: #fff;
		font-size: 0.78rem;
		text-align: left;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	@media (max-width: 640px) {
		.nav span {
			width: 38px;
			height: 56px;
			font-size: 1.7rem;
		}
	}
</style>
