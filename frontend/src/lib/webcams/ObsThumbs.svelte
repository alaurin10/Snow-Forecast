<!--
  A field report's photos as a row of small squares (at most four, the last saying how many
  more there are), each opening the full-screen viewer at that photo. A Ctrl/⌘ or middle
  click opens the photo itself in a new tab.
-->
<script lang="ts">
	import { safeHref, safeImage } from '../links';
	import type { ObsPhoto } from '../types.gen';

	interface Props {
		photos: ObsPhoto[];
		/** The report's title, for the photos' names. */
		title?: string;
		/** Open photo `i` (of `photos`) in the viewer. */
		onopen: (i: number, e: MouseEvent) => void;
	}

	let { photos, title = '', onopen }: Props = $props();
	const MAX = 4;
	const shown = $derived(photos.filter((ph) => safeImage(ph.thumb) && safeImage(ph.url)));
	const name = $derived(title || 'this report');
</script>

{#if shown.length}
	<div class="thumbs">
		{#each shown.slice(0, MAX) as ph, i (i)}
			{@const more = i === MAX - 1 && shown.length > MAX}
			<!-- External image: resolve() is only for routes in this app. -->
			<!-- eslint-disable svelte/no-navigation-without-resolve -->
			<a
				href={safeHref(ph.url)}
				target="_blank"
				rel="noopener noreferrer"
				aria-haspopup="dialog"
				aria-label={more
					? `${shown.length} photos from “${name}”, full screen`
					: `Photo ${i + 1} from “${name}”, full screen`}
				onclick={(e) => {
					if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
					onopen(photos.indexOf(ph), e);
				}}
			>
				<!-- eslint-enable svelte/no-navigation-without-resolve -->
				<img src={safeImage(ph.thumb)} alt="" loading="lazy" referrerpolicy="no-referrer" />
				{#if more}<span class="more-pics">+{shown.length - MAX + 1}</span>{/if}
			</a>
		{/each}
	</div>
{/if}

<style>
	.thumbs {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 96px));
		gap: 6px;
	}
	a {
		position: relative;
		display: block;
		cursor: zoom-in;
	}
	img {
		display: block;
		width: 100%;
		aspect-ratio: 1;
		object-fit: cover;
		border-radius: 6px;
		background: var(--surface-2);
	}
	.more-pics {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		border-radius: 6px;
		background: rgb(8 14 28 / 0.55);
		color: #fff;
		font-weight: 700;
	}
</style>
