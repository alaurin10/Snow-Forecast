<!--
  The one panel a tap on the map opens, whatever was tapped (a station, a field report, a
  hut, a run, a glacier, an avalanche zone, the spot itself), so it always opens in the
  same place: docked to the right edge on desktop, a bottom sheet above the tab bar on
  phones and tablets (a peek or most of the map: a swipe anywhere on it, or a tap on its
  title bar). A fixed header (what it is, its name,
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
	/** While the sheet is dragged: its height in pixels. */
	let dragH = $state<number | null>(null);
	let body = $state<HTMLElement>();

	// A new target starts at the top of its content.
	$effect(() => {
		void active;
		void title;
		if (body) body.scrollTop = 0;
	});

	// ---- The sheet (phones and tablets) moves with a finger anywhere on it -------------
	// At the peek, a swipe up anywhere grows it (its content doesn't scroll yet), and a
	// swipe down puts it away. Grown, the content scrolls; pulled down from the top of its
	// content, the sheet shrinks again. A tap on the title bar switches between the two.
	const sheetLayout = () =>
		typeof matchMedia === 'function' && matchMedia('(max-width: 1099px)').matches;
	interface Gesture {
		y0: number;
		h0: number;
		max: number;
		/** Not yet decided; moving the sheet; scrolling its content. */
		mode: 'wait' | 'sheet' | 'scroll';
		/** It started on the title bar (not one of its buttons). */
		grip: boolean;
		dy: number;
	}
	let g: Gesture | null = null;

	function start(y: number, target: Element) {
		if (!el || !sheetLayout()) return;
		const box = el.parentElement?.getBoundingClientRect();
		if (!box) return;
		g = {
			y0: y,
			h0: el.getBoundingClientRect().height,
			max: box.height,
			mode: 'wait',
			grip: !!target.closest('.grip') && !target.closest('button:not(.handle)'),
			dy: 0
		};
	}
	/** True when this move is the sheet's (the browser mustn't scroll for it). */
	function moveTo(y: number): boolean {
		if (!g) return false;
		const dy = y - g.y0;
		g.dy = dy;
		if (g.mode === 'wait') {
			if (Math.abs(dy) < 4) return g.grip || !full;
			const atTop = (body?.scrollTop ?? 0) <= 0;
			g.mode = g.grip || !full || (dy > 0 && atTop) ? 'sheet' : 'scroll';
		}
		if (g.mode !== 'sheet') return false;
		dragH = Math.max(40, Math.min(g.max * FULL, g.h0 - dy));
		return true;
	}
	function end() {
		if (!g) return;
		const { mode, dy, grip, max } = g;
		g = null;
		// A tap on the title bar.
		if (mode === 'wait') {
			if (grip) full = !full;
			return;
		}
		if (mode !== 'sheet') return;
		const h = dragH ?? 0;
		dragH = null;
		if (dy < -24) full = true;
		else if (dy > 24) {
			// Pulled well below the peek: put away.
			if (h < max * PEEK * 0.6) return onclose();
			full = false;
		}
	}
	function cancel() {
		g = null;
		dragH = null;
	}
	// Touch: listened for directly, so a move can be kept from scrolling the page.
	$effect(() => {
		const node = el;
		if (!node) return;
		const ts = (e: TouchEvent) =>
			e.touches.length === 1 ? start(e.touches[0].clientY, e.target as Element) : cancel();
		const tm = (e: TouchEvent) => {
			if (e.touches.length !== 1) return;
			if (moveTo(e.touches[0].clientY) && e.cancelable) e.preventDefault();
		};
		node.addEventListener('touchstart', ts, { passive: true });
		node.addEventListener('touchmove', tm, { passive: false });
		node.addEventListener('touchend', end);
		node.addEventListener('touchcancel', cancel);
		return () => {
			node.removeEventListener('touchstart', ts);
			node.removeEventListener('touchmove', tm);
			node.removeEventListener('touchend', end);
			node.removeEventListener('touchcancel', cancel);
		};
	});
	// A mouse (a narrow desktop window) drags or taps the title bar.
	function pdown(e: PointerEvent) {
		if (e.pointerType === 'touch') return;
		start(e.clientY, e.target as Element);
		if (g?.grip) (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		else g = null;
	}
	// The wheel, at the peek, grows the sheet before anything scrolls.
	function wheel(e: WheelEvent) {
		if (full || e.deltaY <= 0 || !sheetLayout()) return;
		e.preventDefault();
		full = true;
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
	onwheel={wheel}
	style:--peek={PEEK}
	style:--full={FULL}
	style:--drag-h={dragH != null ? `${dragH}px` : null}
>
	<div
		class="grip"
		role="presentation"
		onpointerdown={pdown}
		onpointermove={(e) => e.pointerType !== 'touch' && moveTo(e.clientY)}
		onpointerup={(e) => e.pointerType !== 'touch' && end()}
		onpointercancel={(e) => e.pointerType !== 'touch' && cancel()}
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
		/* A finger anywhere on the sheet moves it (see the script); grown, its content
		   scrolls, and its chips scroll sideways. */
		.mappanel {
			touch-action: none;
		}
		.mappanel:not(.full) .body {
			overflow-y: hidden;
		}
		.mappanel.full .body {
			touch-action: pan-y;
		}
		.chips {
			touch-action: pan-x;
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
