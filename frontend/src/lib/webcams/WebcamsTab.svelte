<!--
  The Webcams tab: the cameras the owner added on the Manage page. Each shows its
  picture (refreshed every few minutes while the page is in view); a camera with live
  video plays it right here on "Live", from the camera's host, one at a time. Nothing
  from the video host loads until then.
-->
<script lang="ts">
	import { safeHref, safeImage } from '../links';
	import { embedFor, freshImage, playSrc } from '../webcams';
	import type { Webcam } from '../types.gen';

	interface Props {
		cams: Webcam[];
	}

	let { cams }: Props = $props();

	const REFRESH_MS = 5 * 60_000;
	let playing = $state<number | null>(null);
	let broken = $state<Record<number, boolean>>({});
	// Pictures that failed with the refresh marker: shown without it (and not refreshed).
	let plain = $state<Record<number, boolean>>({});
	let tick = $state(0);

	const rows = $derived(
		cams.map((cam) => {
			const embed = embedFor(cam.video_url);
			return { cam, embed, still: safeImage(cam.image_url) ?? embed?.poster };
		})
	);

	// A new picture every few minutes, only while someone is looking.
	$effect(() => {
		let last = Date.now();
		const refresh = () => {
			if (document.visibilityState !== 'visible' || Date.now() - last < REFRESH_MS) return;
			last = Date.now();
			tick = last;
			broken = {};
		};
		const timer = setInterval(refresh, 30_000);
		document.addEventListener('visibilitychange', refresh);
		return () => {
			clearInterval(timer);
			document.removeEventListener('visibilitychange', refresh);
		};
	});

	function failed(i: number) {
		if (tick && !plain[i]) plain = { ...plain, [i]: true };
		else broken = { ...broken, [i]: true };
	}
</script>

<div class="cams">
	{#each rows as { cam, embed, still }, i (i)}
		<article class="card cam">
			<div class="media">
				{#if playing === i && embed}
					<!-- Only the hosts in webcams.ts get here, and the site's CSP frames only those. -->
					<iframe
						src={playSrc(embed)}
						title={`${cam.name} live video`}
						allow="autoplay; fullscreen; picture-in-picture; encrypted-media"
						allowfullscreen
						referrerpolicy="strict-origin-when-cross-origin"
						sandbox="allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox"
					></iframe>
				{:else}
					{#if still && !broken[i]}
						<img
							src={plain[i] ? still : freshImage(still, tick)}
							alt={`${cam.name} webcam`}
							loading="lazy"
							referrerpolicy="no-referrer"
							onerror={() => failed(i)}
						/>
					{:else if !embed}
						<div class="none faint">No picture right now</div>
					{/if}
					{#if embed}
						<button
							type="button"
							class="play"
							aria-label={`Play ${cam.name} live`}
							onclick={() => (playing = i)}
						>
							<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"
								><path d="M7 5v14l12-7z" fill="currentColor" /></svg
							>
							Live
						</button>
					{/if}
				{/if}
			</div>
			<div class="foot">
				<h2>{cam.name}</h2>
				{#if playing === i}
					<button type="button" class="btn small" onclick={() => (playing = null)}>Stop</button>
				{/if}
				<!-- External sites: resolve() is only for routes in this app. -->
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<a class="site" href={safeHref(cam.url)} target="_blank" rel="noopener noreferrer"
					>Open site ↗</a
				>
			</div>
		</article>
	{/each}
</div>
<p class="faint small note">
	Pictures load from each camera's own website. Live video loads from its host (YouTube, Brownrice,
	CamStreamer, Roundshot or Ozolio) only when you press Live.
</p>

<style>
	.cams {
		display: grid;
		gap: 16px;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
	}
	.cam {
		display: grid;
		gap: 10px;
		align-content: start;
	}
	.media {
		position: relative;
		aspect-ratio: 16 / 9;
		border-radius: 10px;
		overflow: hidden;
		background: var(--surface-2);
	}
	img,
	iframe,
	.none {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		border: 0;
	}
	img {
		object-fit: cover;
	}
	.none {
		display: grid;
		place-items: center;
		font-size: 0.85rem;
	}
	.play {
		position: absolute;
		left: 50%;
		top: 50%;
		translate: -50% -50%;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 10px 18px;
		border: 0;
		border-radius: 999px;
		background: rgba(10, 16, 28, 0.72);
		color: #fff;
		font: inherit;
		font-weight: 600;
		cursor: pointer;
		box-shadow: 0 4px 14px rgba(0, 0, 0, 0.3);
	}
	.play:hover {
		background: rgba(10, 16, 28, 0.88);
	}
	.play:focus-visible {
		outline: 2px solid #fff;
		outline-offset: 2px;
	}
	.foot {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.foot h2 {
		margin: 0;
		flex: 1;
		min-width: 0;
		font-size: 1rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.site {
		font-size: 0.85rem;
		white-space: nowrap;
	}
	.note {
		margin: 12px 4px 0;
	}
	@media (max-width: 640px) {
		.cams {
			gap: 12px;
		}
	}
</style>
