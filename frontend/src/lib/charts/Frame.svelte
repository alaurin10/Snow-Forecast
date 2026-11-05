<!--
  The frame every chart draws in: a header (title + the value at the crosshair),
  then an SVG plot with gridlines and labels for at most ONE y scale. There is
  deliberately no way to pass a second scale, so a dual-axis chart can't be built.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { ScaleLinear } from 'd3-scale';
	import type { Margin } from './geom';

	interface Props {
		title: string;
		readout?: string;
		width: number;
		height: number;
		margin: Margin;
		/** The one y scale, range [innerHeight, 0]. Omit for strip charts. */
		y?: ScaleLinear<number, number>;
		yTicks?: number[];
		yFormat?: (v: number) => string;
		/** Crosshair position inside the plot area, in px. */
		crossX?: number | null;
		onpointer?: (px: number) => void;
		onleave?: () => void;
		label?: string;
		children: Snippet<[{ iw: number; ih: number }]>;
		below?: Snippet<[{ iw: number; ih: number }]>;
	}

	let {
		title,
		readout = '',
		width,
		height,
		margin,
		y,
		yTicks = [],
		yFormat = (v: number) => String(v),
		crossX = null,
		onpointer,
		onleave,
		label,
		children,
		below
	}: Props = $props();

	const iw = $derived(Math.max(0, width - margin.left - margin.right));
	const ih = $derived(Math.max(0, height - margin.top - margin.bottom));

	function pointerX(e: PointerEvent): number {
		const box = (e.currentTarget as SVGRectElement).getBoundingClientRect();
		return e.clientX - box.left;
	}
</script>

<figure class="frame">
	<figcaption>
		<span class="title">{title}</span>
		<span class="readout num">{readout}</span>
	</figcaption>
	{#if width > 0}
		<svg {width} {height} role="img" aria-label={label ?? title}>
			<g class="plot" transform="translate({margin.left},{margin.top})" data-iw={iw} data-ih={ih}>
				{#if y}
					{#each yTicks as t (t)}
						<line class="grid" x1="0" x2={iw} y1={y(t)} y2={y(t)} />
						<text class="tick" x="-6" y={y(t)} dy="0.32em" text-anchor="end">{yFormat(t)}</text>
					{/each}
				{/if}
				{@render children({ iw, ih })}
				{#if below}{@render below({ iw, ih })}{/if}
				{#if crossX !== null && crossX >= 0 && crossX <= iw}
					<line class="cross" x1={crossX} x2={crossX} y1="0" y2={ih} />
				{/if}
				{#if onpointer}
					<rect
						class="hit"
						x="0"
						y="0"
						width={iw}
						height={ih}
						role="presentation"
						onpointerdown={(e) => onpointer(pointerX(e))}
						onpointermove={(e) => onpointer(pointerX(e))}
						onpointerleave={(e) => e.pointerType === 'mouse' && onleave?.()}
					/>
				{/if}
			</g>
		</svg>
	{/if}
</figure>

<style>
	.frame {
		margin: 0;
	}
	figcaption {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 8px;
		font-size: 0.8rem;
		margin: 0 0 2px;
	}
	.title {
		color: var(--text-2);
		font-weight: 600;
	}
	.readout {
		color: var(--text);
		font-size: 0.9rem;
		text-align: right;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	svg {
		display: block;
		overflow: visible;
	}
	.grid {
		stroke: var(--grid);
		stroke-width: 1;
	}
	.tick {
		fill: var(--text-3);
		font-size: 10.5px;
		font-variant-numeric: tabular-nums;
	}
	.cross {
		stroke: var(--text);
		stroke-width: 1;
		opacity: 0.55;
		pointer-events: none;
	}
	.hit {
		fill: transparent;
		touch-action: pan-y;
		cursor: crosshair;
	}
</style>
