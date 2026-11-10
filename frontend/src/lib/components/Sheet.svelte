<!-- A popup: a bottom sheet on phones, a centred panel on wider screens. It keeps you
     where you are; the page behind is dimmed and inert until it closes. -->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { modal } from '../modal';

	interface Props {
		title: string;
		sub?: string;
		/** Panel width on wider screens. */
		width?: number;
		onclose: () => void;
		children: Snippet;
	}

	let { title, sub = '', width = 600, onclose, children }: Props = $props();
	const id = `sheet-${Math.random().toString(36).slice(2, 8)}`;
</script>

<div class="modal" use:modal={{ onclose }}>
	<div class="scrim" role="presentation" onclick={onclose}></div>
	<div
		class="sheet"
		role="dialog"
		aria-modal="true"
		aria-labelledby={id}
		tabindex="-1"
		style:--w="{width}px"
	>
		<header>
			<div>
				<h3 {id}>{title}</h3>
				{#if sub}<div class="sub">{sub}</div>{/if}
			</div>
			<button class="close" onclick={onclose} aria-label="Close">✕</button>
		</header>
		{@render children()}
	</div>
</div>

<style>
	.modal {
		display: contents;
	}
	.scrim {
		position: fixed;
		inset: 0;
		background: rgb(8 14 28 / 0.42);
		z-index: 40;
	}
	.sheet {
		position: fixed;
		z-index: 41;
		left: 0;
		right: 0;
		bottom: 0;
		max-height: 92vh;
		overflow-y: auto;
		display: grid;
		gap: 12px;
		padding: 16px 16px calc(20px + env(safe-area-inset-bottom));
		background: var(--surface);
		color: var(--text);
		border: 1px solid var(--panel-rim);
		border-radius: var(--radius) var(--radius) 0 0;
		box-shadow: 0 -10px 40px rgb(0 0 0 / 0.3);
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 12px;
	}
	h3 {
		margin: 0;
		font-family: var(--font-num);
		font-size: 1.15rem;
		font-weight: 700;
		letter-spacing: -0.01em;
	}
	.sub {
		margin-top: 2px;
		font-size: 0.82rem;
		color: var(--text-2);
	}
	.close {
		flex: 0 0 auto;
		width: 40px;
		height: 40px;
		border: 1px solid var(--border);
		background: var(--surface-2);
		border-radius: 999px;
		cursor: pointer;
	}
	.close:hover {
		background: var(--hover);
	}
	@media (min-width: 641px) {
		.sheet {
			left: 50%;
			right: auto;
			bottom: auto;
			top: 50%;
			width: min(var(--w), calc(100vw - 48px));
			max-height: min(88vh, 900px);
			transform: translate(-50%, -50%);
			border-radius: var(--radius);
			padding: 18px 20px 20px;
		}
	}
</style>
