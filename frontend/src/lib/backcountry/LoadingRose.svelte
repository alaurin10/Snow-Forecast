<!--
  Where wind would drift new snow: each wedge is the share of snowfall × ridge
  wind coming from that direction (N at the top, clockwise). Snow loads on the
  opposite, lee aspects, which the label below names.
-->
<script lang="ts">
	import type { RoseOut } from '../types.gen';
	import { snow, speed, type UnitSystem } from '../units';

	interface Props {
		rose: RoseOut;
		title: string;
		units: UnitSystem;
		size?: number;
	}

	let { rose, title, units, size = 132 }: Props = $props();

	const PAD = 14; // room for the compass letters
	const c = $derived(size / 2);
	const R = $derived(size / 2 - PAD);
	const top = $derived(Math.max(...rose.sectors, 0));

	function point(angleDeg: number, r: number): [number, number] {
		const a = ((angleDeg - 90) * Math.PI) / 180;
		return [c + r * Math.cos(a), c + r * Math.sin(a)];
	}

	function wedge(i: number, share: number): string {
		// Area, not radius, follows the share.
		const r = top > 0 ? R * Math.sqrt(share / top) : 0;
		const [x1, y1] = point(i * 45 - 20, r);
		const [x2, y2] = point(i * 45 + 20, r);
		return `M${c},${c} L${x1.toFixed(1)},${y1.toFixed(1)} A${r.toFixed(1)},${r.toFixed(1)} 0 0 1 ${x2.toFixed(1)},${y2.toFixed(1)} Z`;
	}
	const LETTERS = [
		{ t: 'N', a: 0 },
		{ t: 'E', a: 90 },
		{ t: 'S', a: 180 },
		{ t: 'W', a: 270 }
	];
	const described = $derived(
		`${title}: ${rose.label}. ${snow(rose.snow_cm, units)} of snow` +
			(rose.mean_kmh !== null ? `, wind about ${speed(rose.mean_kmh, units)}` : '')
	);
</script>

<figure class="rose">
	<figcaption>
		<span class="t">{title}</span>
		<span class="muted"
			>{snow(rose.snow_cm, units)} snow{rose.mean_kmh !== null
				? ` · ${speed(rose.mean_kmh, units)} wind`
				: ''}</span
		>
	</figcaption>
	<svg width={size} height={size} viewBox="0 0 {size} {size}" role="img" aria-label={described}>
		<g class="plot" data-iw={size} data-ih={size}>
			<circle class="ring" cx={c} cy={c} r={R} />
			<circle class="ring" cx={c} cy={c} r={R / 2} />
			{#each rose.sectors as share, i (i)}
				{#if share > 0}
					<path class="mark" d={wedge(i, share)} />
				{/if}
			{/each}
			{#each LETTERS as l (l.t)}
				{@const [x, y] = point(l.a, R + 7)}
				<text class="letter" {x} {y} dy="0.35em" text-anchor="middle">{l.t}</text>
			{/each}
		</g>
	</svg>
	<p class="label">{rose.label}</p>
</figure>

<style>
	.rose {
		margin: 0;
		display: grid;
		justify-items: center;
		gap: 2px;
		min-width: 0;
	}
	figcaption {
		display: grid;
		justify-items: center;
		font-size: 0.8rem;
	}
	.t {
		font-weight: 600;
	}
	.ring {
		fill: none;
		stroke: var(--grid);
	}
	.mark {
		fill: var(--wind);
		fill-opacity: 0.75;
		stroke: var(--wind);
	}
	.letter {
		fill: var(--text-3);
		font-size: 10px;
	}
	.label {
		margin: 0;
		font-size: 0.82rem;
		text-align: center;
	}
</style>
