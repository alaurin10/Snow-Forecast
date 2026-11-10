<!-- Preview of a share image with its shape (3:4 or 4:3) and any extra options, then
     Share (the phone's share sheet: Messages, AirDrop, Save Image…), Save or Copy. The
     image is made before the Share tap because iOS only opens the share sheet straight
     from a tap. A bottom sheet on phones, a centred dialog on wider screens. -->
<script lang="ts">
	import { modal } from '../modal';
	import type { Snippet } from 'svelte';
	import { ensureFonts, toBlob, type Shape } from './canvas';

	interface Props {
		title: string;
		/** File name without extension, e.g. "whistler-snow-5-days". */
		filename: string;
		/** Draw the image. Runs again when the shape or anything it reads changes. */
		render: (shape: Shape) => HTMLCanvasElement;
		/** Extra controls above the preview, e.g. how many days. */
		options?: Snippet;
		onclose: () => void;
	}

	let { title, filename, render, options, onclose }: Props = $props();

	const SHAPE_KEY = 'share-shape';
	const savedShape = (): Shape => {
		try {
			return localStorage.getItem(SHAPE_KEY) === 'landscape' ? 'landscape' : 'portrait';
		} catch {
			return 'portrait';
		}
	};
	let shape = $state<Shape>(savedShape());
	const setShape = (s: Shape) => {
		shape = s;
		try {
			localStorage.setItem(SHAPE_KEY, s);
		} catch {
			/* private mode: the choice lasts this visit only */
		}
	};

	let fontsReady = $state(false);
	let file = $state<File | null>(null);
	let url = $state<string | null>(null);
	let error = $state<string | null>(null);
	let note = $state<string | null>(null);

	$effect(() => {
		ensureFonts().then(() => (fontsReady = true));
	});

	// Re-draw whenever the shape or the card's data changes.
	$effect(() => {
		if (!fontsReady) return;
		let canvas: HTMLCanvasElement;
		try {
			canvas = render(shape);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			return;
		}
		let stale = false;
		toBlob(canvas)
			.then((blob) => {
				if (stale) return;
				file = new File([blob], `${filename}.png`, { type: 'image/png' });
				const next = URL.createObjectURL(blob);
				if (url) URL.revokeObjectURL(url);
				url = next;
				error = null;
			})
			.catch((e: Error) => (error = e.message));
		return () => (stale = true);
	});
	$effect(() => () => {
		if (url) URL.revokeObjectURL(url);
	});

	const canShareFiles = $derived.by(() => {
		if (!file || typeof navigator === 'undefined' || !navigator.canShare) return false;
		try {
			return navigator.canShare({ files: [file] });
		} catch {
			return false;
		}
	});
	const canCopy = $derived(
		typeof window !== 'undefined' &&
			typeof ClipboardItem !== 'undefined' &&
			!!navigator.clipboard?.write
	);

	async function share() {
		if (!file) return;
		note = null;
		try {
			await navigator.share({ files: [file], title });
		} catch (e) {
			// Closing the share sheet is not an error.
			if (e instanceof Error && e.name !== 'AbortError') note = `Couldn't share: ${e.message}`;
		}
	}
	function save() {
		if (!url || !file) return;
		const a = document.createElement('a');
		a.href = url;
		a.download = file.name;
		document.body.appendChild(a);
		a.click();
		a.remove();
	}
	async function copy() {
		if (!file) return;
		try {
			await navigator.clipboard.write([new ClipboardItem({ 'image/png': file })]);
			note = 'Copied. Paste it into a message.';
		} catch (e) {
			note = `Couldn't copy: ${e instanceof Error ? e.message : e}`;
		}
	}
</script>

<div class="modal" use:modal={{ onclose }}>
	<div class="scrim" role="presentation" onclick={onclose}></div>
	<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="share-title" tabindex="-1">
		<header>
			<h3 id="share-title">{title}</h3>
			<button class="close" onclick={onclose} aria-label="Close">✕</button>
		</header>

		<div class="controls">
			<div class="seg" role="group" aria-label="Image shape">
				<button aria-pressed={shape === 'portrait'} onclick={() => setShape('portrait')}
					>Portrait 3:4</button
				>
				<button aria-pressed={shape === 'landscape'} onclick={() => setShape('landscape')}
					>Landscape 4:3</button
				>
			</div>
			{#if options}{@render options()}{/if}
		</div>

		<div class="preview" class:landscape={shape === 'landscape'}>
			{#if error}
				<p class="muted">Couldn't make the image: {error}</p>
			{:else if url}
				<img src={url} alt="What will be shared" />
			{:else}
				<p class="muted">Making the image…</p>
			{/if}
		</div>

		<div class="actions">
			{#if canShareFiles}
				<button class="btn primary big" onclick={share} disabled={!file}>
					<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
						><path d="M12 3v12M7 8l5-5 5 5M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7" /></svg
					>
					Share
				</button>
			{/if}
			<button class="btn big" class:primary={!canShareFiles} onclick={save} disabled={!file}
				>Save image</button
			>
			{#if canCopy}
				<button class="btn big" onclick={copy} disabled={!file}>Copy</button>
			{/if}
		</div>
		{#if note}<p class="note muted" role="status">{note}</p>{/if}
	</div>
</div>

<style>
	.modal {
		display: contents;
	}
	.scrim {
		position: fixed;
		inset: 0;
		background: rgb(0 0 0 / 0.4);
		z-index: 40;
	}
	.sheet {
		position: fixed;
		z-index: 41;
		left: 0;
		right: 0;
		bottom: 0;
		max-height: 92dvh;
		overflow-y: auto;
		display: grid;
		gap: 12px;
		padding: 14px 16px calc(18px + env(safe-area-inset-bottom));
		background: var(--surface);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 18px 18px 0 0;
		box-shadow: 0 -8px 30px rgb(0 0 0 / 0.2);
	}
	@media (min-width: 768px) {
		.sheet {
			left: 50%;
			right: auto;
			top: 50%;
			bottom: auto;
			width: min(560px, calc(100vw - 48px));
			max-height: calc(100dvh - 48px);
			transform: translate(-50%, -50%);
			border-radius: var(--radius);
			padding: 18px 20px 20px;
		}
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
	}
	h3 {
		margin: 0;
		font-size: 1.05rem;
	}
	.close {
		border: 1px solid var(--border);
		background: var(--surface-2);
		border-radius: 999px;
		width: 34px;
		height: 34px;
		flex-shrink: 0;
		cursor: pointer;
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
	}
	.preview {
		display: grid;
		place-items: center;
		min-height: 200px;
		background: var(--surface-2);
		border-radius: 14px;
		padding: 10px;
	}
	.preview img {
		display: block;
		max-width: 100%;
		max-height: 52dvh;
		border-radius: 10px;
		box-shadow: 0 4px 18px rgb(0 0 0 / 0.15);
	}
	.preview.landscape img {
		max-height: 40dvh;
	}
	.actions {
		display: flex;
		gap: 8px;
	}
	.btn.big {
		flex: 1;
		display: inline-flex;
		justify-content: center;
		align-items: center;
		gap: 8px;
		padding: 11px 16px;
		font-size: 0.95rem;
		font-weight: 600;
	}
	.btn svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2.2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.note {
		margin: 0;
		font-size: 0.85rem;
	}
</style>
