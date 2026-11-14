<!--
  Where an avalanche problem is, as the bulletin lists it: eight aspects around (north
  at the top), three rings for elevation (alpine in the middle, below treeline outside).
  Filled cells are the listed ones. It only redraws the bulletin's own words.
-->
<script lang="ts">
	interface Props {
		aspects: string[];
		elevations: string[];
		size?: number;
	}

	let { aspects, elevations, size = 60 }: Props = $props();
	const SECTORS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
	const RINGS = ['alpine', 'treeline', 'below'];
	const c = $derived(size / 2);
	const R = $derived(size / 2 - 7);
	// With no elevations listed, the aspects apply at every one.
	const bands = $derived(elevations.length ? elevations : RINGS);

	function point(angle: number, r: number): string {
		const a = ((angle - 90) * Math.PI) / 180;
		return `${(c + r * Math.cos(a)).toFixed(1)},${(c + r * Math.sin(a)).toFixed(1)}`;
	}
	function cellPath(sector: number, ring: number): string {
		const r0 = (R * ring) / 3;
		const r1 = (R * (ring + 1)) / 3;
		const a0 = sector * 45 - 22.5;
		const a1 = sector * 45 + 22.5;
		const inner = r0 === 0 ? `L${c},${c}` : `L${point(a1, r0)} A${r0},${r0} 0 0 0 ${point(a0, r0)}`;
		return `M${point(a0, r1)} A${r1},${r1} 0 0 1 ${point(a1, r1)} ${inner} Z`;
	}
	const label = $derived(
		`${aspects.join(', ')} aspects` + (elevations.length ? `; ${elevations.join(', ')}` : '')
	);
</script>

<svg
	class="prose"
	width={size}
	height={size}
	viewBox="0 0 {size} {size}"
	role="img"
	aria-label={label}
>
	{#each SECTORS as s, i (s)}
		{#each RINGS as ring, k (ring)}
			<path d={cellPath(i, k)} class:on={aspects.includes(s) && bands.includes(ring)} />
		{/each}
	{/each}
	<text x={c} y="5.5" text-anchor="middle">N</text>
</svg>

<style>
	.prose {
		flex: none;
		display: block;
	}
	path {
		fill: var(--surface-2);
		stroke: var(--surface);
		stroke-width: 1;
	}
	path.on {
		fill: var(--text);
		fill-opacity: 0.78;
	}
	text {
		fill: var(--text-3);
		font-size: 7.5px;
		font-weight: 600;
	}
</style>
