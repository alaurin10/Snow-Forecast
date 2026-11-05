<!-- Webcams the owner added on the Manage page: a still image when there is one, always a link. -->
<script lang="ts">
	import type { Webcam } from '../types.gen';

	interface Props {
		cams: Webcam[];
	}

	let { cams }: Props = $props();
	let broken = $state<Record<number, boolean>>({});
</script>

{#if cams.length}
	<section class="card">
		<h2>Webcams</h2>
		<div class="cams">
			{#each cams as cam, i (i)}
				<!-- External sites: resolve() is only for routes in this app. -->
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<a class="cam" href={cam.url} target="_blank" rel="noopener">
					{#if cam.image_url && !broken[i]}
						<img
							src={cam.image_url}
							alt={`${cam.name} webcam`}
							loading="lazy"
							referrerpolicy="no-referrer"
							onerror={() => (broken = { ...broken, [i]: true })}
						/>
					{/if}
					<span>{cam.name} ↗</span>
				</a>
			{/each}
		</div>
	</section>
{/if}

<style>
	h2 {
		margin: 0 0 8px;
	}
	.cams {
		display: grid;
		gap: 8px;
		grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
	}
	.cam {
		display: grid;
		gap: 4px;
		color: var(--text);
		text-decoration: none;
		font-size: 0.85rem;
	}
	img {
		width: 100%;
		aspect-ratio: 16 / 9;
		object-fit: cover;
		border-radius: 8px;
		background: var(--surface-2);
	}
</style>
