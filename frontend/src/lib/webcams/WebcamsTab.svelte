<!--
  The Webcams tab: the cameras the owner added on the Manage page. Each shows its
  picture (refreshed every few minutes while the page is in view); a camera with live
  video plays it right here on "Live", from the camera's host, one at a time and across
  the whole row. "Play all live" starts every camera at once, and this device remembers
  it, so the next visit starts them too. Otherwise nothing loads from a video host.
  Below them, photos from recent field reports nearby (FieldPhotos).
-->
<script lang="ts">
	import { safeHref, safeImage } from '../links';
	import { embedFor, freshImage, playSrc } from '../webcams';
	import type { NearbyOut, Webcam } from '../types.gen';
	import type { UnitSystem } from '../units';
	import FieldPhotos from './FieldPhotos.svelte';
	import { prefs } from '../prefs.svelte';
	import { untrack } from 'svelte';

	interface Props {
		cams: Webcam[];
		/** Field reports around the location, for their photos (loaded with the page). */
		nearby?: NearbyOut | null;
		units?: UnitSystem;
		tz?: string | null;
	}

	let { cams, nearby = null, units = 'imperial', tz = null }: Props = $props();

	const REFRESH_MS = 5 * 60_000;
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
	/** The cameras with live video. */
	const lives = $derived(rows.flatMap((r, i) => (r.embed ? [i] : [])));
	const all = $derived(prefs.camsAutoplay === 'on');
	// Which cameras are playing. "All" mode is the remembered choice on this device; a
	// new location (new cameras) starts from it again.
	let playing = $state<Set<number>>(new Set());
	// Keyed on the cameras themselves, not the list: a refreshed forecast brings the same
	// cameras in a new list, and must not stop a video someone is watching.
	const camsKey = $derived(cams.map((c) => `${c.name}|${c.video_url ?? ''}`).join('\n'));
	$effect.pre(() => {
		void camsKey;
		const on = all;
		playing = new Set(on ? untrack(() => lives) : []);
	});
	// Just one camera playing (or just one camera): it takes the whole row.
	const wide = $derived(rows.length === 1 ? 0 : playing.size === 1 ? [...playing][0] : -1);

	function play(i: number) {
		playing = new Set(all ? [...playing, i] : [i]);
	}
	function stop(i: number) {
		playing = new Set([...playing].filter((j) => j !== i));
	}
	function playAll(on: boolean) {
		prefs.setCamsAutoplay(on);
		playing = new Set(on ? lives : []);
	}

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

{#if cams.length}
	{#if lives.length > 1}
		<div class="bar">
			<button
				type="button"
				class="btn small"
				aria-pressed={all}
				title="Remembered on this device. Live video uses more data, mostly on phones."
				onclick={() => playAll(!all)}
			>
				{all ? 'Stop all' : `Play all live (${lives.length})`}
			</button>
			<span class="faint small">
				{all
					? 'Live video starts by itself on this device.'
					: 'Starts every camera at once; this device remembers it.'}
			</span>
		</div>
	{/if}
	<div class="cams">
		{#each rows as { cam, embed, still }, i (i)}
			<article class="card cam" class:wide={wide === i}>
				<div class="media">
					{#if playing.has(i) && embed}
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
								onclick={() => play(i)}
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
					{#if playing.has(i)}
						<button type="button" class="btn small" onclick={() => stop(i)}>Stop</button>
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
		Pictures load from each camera's own website. Live video loads from its host (YouTube,
		Brownrice, CamStreamer, Roundshot or Ozolio) only when you press Live or Play all.
	</p>
{/if}
{#if nearby}
	<FieldPhotos data={nearby} {units} {tz} />
{/if}

<style>
	.cams {
		display: grid;
		gap: 16px;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 440px), 1fr));
		/* The cameras after a wide one fill the gap it leaves, so it stays where it was. */
		grid-auto-flow: row dense;
	}
	/* One camera playing: across the whole row, as big as the page allows. */
	.cam.wide {
		grid-column: 1 / -1;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px 12px;
		margin: 0 4px 12px;
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
