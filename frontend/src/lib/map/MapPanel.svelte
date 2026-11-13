<!--
  The one panel a tap on the map opens, whatever was tapped (a station, a field report, a
  hut, a run, a glacier, an avalanche zone, the spot itself), so it always opens in the
  same place: docked to the right edge on desktop, a bottom sheet above the tab bar on
  phones and tablets (peek or full, by its handle). A fixed header (what it is, its name,
  close) and chips for the other things under the tap, which switch the content in place;
  the body scrolls.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		/** What it is, small above the title: "Snow station", "Glacier" … */
		kind: string;
		title: string;
		/** Everything under the tap, as chip labels; shown when there's more than one. */
		chips?: string[];
		active?: number;
		onchip?: (i: number) => void;
		onclose: () => void;
		/** A line under the title (the spot's coordinates). */
		sub?: Snippet;
		children: Snippet;
		/** The panel's element, for the map's padding. */
		el?: HTMLElement;
	}

	let {
		kind,
		title,
		chips = [],
		active = 0,
		onchip,
		onclose,
		sub,
		children,
		el = $bindable()
	}: Props = $props();

	/** Phones and tablets: the sheet's height, as a share of the map's. */
	const PEEK = 0.35;
	const FULL = 0.8;
	let full = $state(false);
	/** While the handle is dragged: the sheet's height in pixels. */
	let dragH = $state<number | null>(null);
	let body = $state<HTMLElement>();
	let drag: { y: number; h: number; max: number; moved: boolean } | null = null;

	// A new target starts at the top of its content.
	$effect(() => {
		void active;
		void title;
		if (body) body.scrollTop = 0;
	});

	/** The whole title bar is the sheet's grip (phones and tablets): drag it up or down,
	 *  or tap it to switch between the peek and most of the map. Its buttons stay buttons. */
	function down(e: PointerEvent) {
		if (!matchMedia('(max-width: 1099px)').matches) return;
		if ((e.target as Element).closest('button:not(.handle)')) return;
		const box = el?.parentElement?.getBoundingClientRect();
		if (!el || !box) return;
		drag = { y: e.clientY, h: el.getBoundingClientRect().height, max: box.height, moved: false };
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	}
	function move(e: PointerEvent) {
		if (!drag) return;
		const dy = e.clientY - drag.y;
		if (!drag.moved && Math.abs(dy) < 6) return;
		drag.moved = true;
		dragH = Math.max(40, Math.min(drag.max * FULL, drag.h - dy));
	}
	function up() {
		if (!drag) return;
		const { moved, max } = drag;
		drag = null;
		if (!moved) {
			full = !full;
			return;
		}
		const h = dragH ?? 0;
		dragH = null;
		// Pulled well below the peek: put away.
		if (h < max * PEEK * 0.6) return onclose();
		full = h > max * ((PEEK + FULL) / 2);
	}
</script>

<div
	class="mappanel"
	class:full
	class:dragging={dragH != null}
	role="dialog"
	aria-label={title}
	data-map-panel
	bind:this={el}
	style:--peek={PEEK}
	style:--full={FULL}
	style:--drag-h={dragH != null ? `${dragH}px` : null}
>
	<div
		class="grip"
		role="presentation"
		onpointerdown={down}
		onpointermove={move}
		onpointerup={up}
		onpointercancel={() => ((drag = null), (dragH = null))}
	>
		<button
			class="handle"
			aria-label={full ? 'Make the panel smaller' : 'Make the panel bigger'}
			aria-expanded={full}
			onkeydown={(e) =>
				(e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), (full = !full))}
		>
			<span aria-hidden="true"></span>
		</button>
		<header>
			<div class="names">
				<span class="kind">{kind}</span>
				<strong class="title" {title}>{title}</strong>
				{#if sub}{@render sub()}{/if}
			</div>
			<button class="x" onclick={onclose} aria-label="Close">✕</button>
		</header>
	</div>
	{#if chips.length > 1}
		<div class="chips" role="group" aria-label="Here">
			{#each chips as c, i (i)}
				<button class="chip" aria-pressed={i === active} onclick={() => onchip?.(i)} title={c}
					>{c}</button
				>
			{/each}
		</div>
	{/if}
	<div class="body" bind:this={body}>
		{@render children()}
	</div>
</div>

<style>
	.mappanel {
		position: absolute;
		top: 10px;
		right: 10px;
		width: 360px;
		max-height: calc(100% - 20px);
		z-index: 1003;
		display: flex;
		flex-direction: column;
		border-radius: 16px;
		border: 1px solid var(--glass-border);
		/* Solid enough to read over busy satellite imagery. */
		background: color-mix(in srgb, var(--surface) 94%, transparent);
		box-shadow: var(--glass-shadow);
		backdrop-filter: var(--blur-glass);
		-webkit-backdrop-filter: var(--blur-glass);
		color: var(--text);
		font-size: 0.85rem;
		overflow: hidden;
		pointer-events: auto;
	}
	.handle {
		display: none;
	}
	header {
		flex: none;
		display: flex;
		align-items: flex-start;
		gap: 8px;
		padding: 10px 8px 6px 14px;
	}
	.names {
		flex: 1;
		min-width: 0;
		display: grid;
		gap: 1px;
	}
	.kind {
		font-size: 0.7rem;
		color: var(--text-2);
		height: 1.1em;
		line-height: 1.1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.title {
		font-size: 1rem;
		line-height: 1.3;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.x {
		flex: none;
		width: 32px;
		height: 32px;
		border: 0;
		border-radius: 10px;
		background: transparent;
		color: var(--text-2);
		font-size: 0.9rem;
		cursor: pointer;
	}
	.x:hover {
		background: var(--hover);
	}
	.chips {
		flex: none;
		display: flex;
		gap: 6px;
		padding: 0 14px 8px;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.chips::-webkit-scrollbar {
		display: none;
	}
	.chip {
		flex: none;
		max-width: 9rem;
		height: 28px;
		padding: 0 11px;
		border-radius: 999px;
		border: 1px solid var(--border);
		background: transparent;
		color: var(--text);
		font: inherit;
		font-size: 0.78rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		cursor: pointer;
	}
	.chip:hover {
		background: var(--hover);
	}
	.chip[aria-pressed='true'] {
		background: var(--accent);
		border-color: transparent;
		color: var(--on-accent);
	}
	.body {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		overscroll-behavior: contain;
		padding: 2px 14px 14px;
		border-top: 1px solid var(--border);
		padding-top: 10px;
	}

	/* Phones and tablets: a bottom sheet above the floating tab bar, at a peek or most of
	   the map's height, whatever it holds. */
	@media (max-width: 1099px) {
		.mappanel {
			top: auto;
			left: 8px;
			right: 8px;
			bottom: calc(84px + env(safe-area-inset-bottom));
			width: auto;
			max-width: 640px;
			margin: 0 auto;
			height: var(--drag-h, calc(100% * var(--peek)));
			max-height: calc(100% - 84px - env(safe-area-inset-bottom) - 10px);
			border-radius: 18px;
			transition: height 260ms cubic-bezier(0.2, 0.8, 0.2, 1);
		}
		.mappanel.full {
			height: var(--drag-h, calc(100% * var(--full)));
		}
		.mappanel.dragging {
			transition: none;
		}
		/* The handle and the title together: one big target, which the map never gets. */
		.grip {
			flex: none;
			cursor: grab;
			touch-action: none;
			user-select: none;
			-webkit-user-select: none;
		}
		.handle {
			display: grid;
			place-items: center;
			height: 22px;
			width: 100%;
			border: 0;
			padding: 0;
			background: transparent;
			cursor: grab;
		}
		.handle span {
			width: 40px;
			height: 5px;
			border-radius: 3px;
			background: var(--text-3);
			opacity: 0.6;
		}
		header {
			padding-top: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.mappanel {
			transition: none;
		}
	}
</style>
