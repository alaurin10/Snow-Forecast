<!--
  Field photos full screen, one at a time: the photo is the focus, as large as the screen
  allows, with a short line under it: where it was taken, who sent it, when, how far away
  and the photo's own caption, and a link to the full report. What the observer wrote
  about the day is on the Backcountry tab, not here. The text keeps well clear of the
  screen's edges, whose corners are rounded on most phones (the app doesn't extend under
  them, so the system's safe-area insets are usually zero and fixed margins do the work).
  Arrows, the arrow keys or a swipe go to the previous or next photo across every report;
  Escape, ✕ or the phone's Back button close it.
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
		onclose: () => void;
	}

	let { photos, index = $bindable(), units, tz = null, onclose }: Props = $props();

	const count = $derived(photos.length);
	const at = $derived(Math.min(Math.max(index, 0), Math.max(count - 1, 0)));
	const cur = $derived(photos[at]);
	const away = (km: number) =>
		units === 'imperial' ? `${(km * 0.621371).toFixed(0)} mi` : `${km.toFixed(0)} km`;
	const meta = $derived(
		cur
			? [
					reportFrom(cur.report),
					reportWhen(cur.report, tz),
					`${away(cur.distance_km)} away`,
					cur.report.region
				]
					.filter(Boolean)
					.join(' · ')
			: ''
	);

	function go(step: number) {
		if (count > 1) index = (at + step + count) % count;
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
		if (e.key === 'ArrowRight') go(1);
		else if (e.key === 'ArrowLeft') go(-1);
		else return;
		e.preventDefault();
	}

	// A sideways swipe (mostly horizontal, 40 px or more) flips.
	let start: { x: number; y: number } | null = null;
	function down(e: PointerEvent) {
		start = { x: e.clientX, y: e.clientY };
	}
	function up(e: PointerEvent) {
		if (!start) return;
		const dx = e.clientX - start.x;
		const dy = e.clientY - start.y;
		start = null;
		if (Math.abs(dx) >= 40 && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? 1 : -1);
	}
</script>

<svelte:window onkeydown={onkey} />

<div class="modal" use:modal={{ onclose }}>
	<div
		class="viewer"
		role="dialog"
		aria-modal="true"
		aria-label="Field photos"
		aria-roledescription="photo viewer"
		tabindex="-1"
	>
		<header>
			<span class="count" aria-live="polite">{at + 1} of {count}</span>
			<button type="button" class="close" onclick={onclose} aria-label="Close photos">✕</button>
		</header>
		<div
			class="stage"
			role="presentation"
			onpointerdown={down}
			onpointerup={up}
			onpointercancel={() => (start = null)}
		>
			{#if cur && safeImage(cur.photo.url)}
				{#key at}
					<img
						src={safeImage(cur.photo.url)}
						alt={cur.photo.caption || `Photo from “${cur.report.title || 'a field report'}”`}
						referrerpolicy="no-referrer"
						draggable="false"
						style:background-image={safeImage(cur.photo.thumb)
							? `url("${safeImage(cur.photo.thumb)}")`
							: undefined}
					/>
				{/key}
			{/if}
			{#if count > 1}
				<button type="button" class="nav prev" onclick={() => go(-1)} aria-label="Previous photo"
					>‹</button
				>
				<button type="button" class="nav next" onclick={() => go(1)} aria-label="Next photo"
					>›</button
				>
			{/if}
		</div>
		{#if cur}
			<div class="foot">
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
					<p class="meta">{meta}</p>
					{#if cur.photo.caption}<p class="caption">{cur.photo.caption}</p>{/if}
				</div>
			</div>
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
		background: #06090f;
		color: #f3f5f8;
		outline: none;
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		/* Clear of rounded corners: the count and ✕ sit well in from the top corners. */
		padding: max(14px, calc(env(safe-area-inset-top) + 8px))
			max(20px, calc(env(safe-area-inset-right) + 12px)) 6px
			max(24px, calc(env(safe-area-inset-left) + 16px));
	}
	.count {
		font-size: 0.85rem;
		color: #c3cad6;
		font-variant-numeric: tabular-nums;
	}
	.close {
		width: 44px;
		height: 44px;
		border: 0;
		border-radius: 50%;
		background: rgb(255 255 255 / 0.1);
		color: inherit;
		font-size: 1.1rem;
		cursor: pointer;
	}
	.stage {
		position: relative;
		display: grid;
		place-items: center;
		min-height: 0;
		touch-action: pan-y pinch-zoom;
		user-select: none;
	}
	/* Fills the space between the bar and the caption, the photo scaled to fit inside it;
	   the small copy shows in the same place until the large one arrives. */
	img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: contain;
		background-size: contain;
		background-repeat: no-repeat;
		background-position: center;
	}
	.nav {
		position: absolute;
		top: 50%;
		translate: 0 -50%;
		width: 48px;
		height: 72px;
		border: 0;
		border-radius: 10px;
		background: rgb(0 0 0 / 0.45);
		color: #fff;
		font-size: 2.2rem;
		line-height: 1;
		cursor: pointer;
	}
	.prev {
		left: 8px;
	}
	.next {
		right: 8px;
	}
	.close:hover,
	.nav:hover {
		background: rgb(255 255 255 / 0.2);
	}
	.close:focus-visible,
	.nav:focus-visible,
	.info a:focus-visible {
		outline: 2px solid #fff;
		outline-offset: 2px;
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
	@media (max-width: 640px) {
		.nav {
			width: 40px;
			height: 60px;
			font-size: 1.8rem;
		}
	}
</style>
