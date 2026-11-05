<!-- Chance of at least X: the share of ensemble members at or above each amount. -->
<script lang="ts">
	import { scaleLinear } from 'd3-scale';
	import { converters, type UnitSystem } from '../units';
	import Frame from './Frame.svelte';

	interface Props {
		title: string;
		/** Member totals in cm (any order). */
		members: number[];
		units: UnitSystem;
		estimated?: boolean;
		width?: number;
	}

	let { title, members, units, estimated = false, width: fixedWidth }: Props = $props();
	let measured = $state(0);

	const W = $derived(fixedWidth ?? measured);
	const c = $derived(converters(units));
	const M = { top: 8, right: 12, bottom: 22, left: 36 };
	const H = 170;
	const vals = $derived(members.map((v) => c.snow(v) ?? 0).sort((a, b) => a - b));
	const iw = $derived(Math.max(0, W - M.left - M.right));
	const xMax = $derived(Math.max(c.snowMarks[2] * 1.15, vals.at(-1) ?? 0));
	const x = $derived(scaleLinear().domain([0, xMax]).range([0, iw]).nice());
	const y = $derived(
		scaleLinear()
			.domain([0, 100])
			.range([H - M.top - M.bottom, 0])
	);
	const chance = (t: number) =>
		vals.length ? (100 * vals.filter((v) => v >= t).length) / vals.length : 0;
	// Step curve: the share drops just after each member's total.
	const path = $derived.by(() => {
		if (!vals.length) return '';
		const pts: string[] = [`M0,${y(100)}`];
		let prev = 100;
		for (const v of vals) {
			const p = chance(v + 1e-9);
			if (p !== prev) {
				pts.push(`H${x(Math.min(v, x.domain()[1]))}V${y(p)}`);
				prev = p;
			}
		}
		pts.push(`H${x(x.domain()[1])}`);
		return pts.join('');
	});
	const marks = $derived(c.snowMarks.map((t) => ({ t, p: Math.round(chance(t)) })));
</script>

<div bind:clientWidth={measured}>
	<Frame
		{title}
		readout={marks.map((m, k) => `≥${m.t}${k === 0 ? ` ${c.snowUnit}` : ''} ${m.p}%`).join(' · ')}
		width={W}
		height={H}
		margin={M}
		{y}
		yTicks={[0, 50, 100]}
		yFormat={(v) => `${v}%`}
		label={`${title}: chance of at least each snow amount`}
	>
		{#snippet children({ ih })}
			{#if vals.length}
				{#each marks as m (m.t)}
					<line class="markline" x1={x(m.t)} x2={x(m.t)} y1="0" y2={ih} />
				{/each}
				<path class="mark curve" d={path} />
				{#each marks as m (m.t)}
					<circle class="mark" cx={x(m.t)} cy={y(m.p)} r="4" />
				{/each}
			{:else}
				<text class="empty" x={10} y={ih / 2}>No ensemble data</text>
			{/if}
		{/snippet}
		{#snippet below({ ih })}
			{#each x.ticks(5) as t (t)}
				<text class="tick" x={x(t)} y={ih + 15} text-anchor="middle">{t}</text>
			{/each}
		{/snippet}
	</Frame>
	{#if estimated}<p class="faint note">Estimated from the mid-mountain ensemble.</p>{/if}
</div>

<style>
	.curve {
		fill: none;
		stroke: var(--snow);
		stroke-width: 2;
	}
	circle.mark {
		fill: var(--snow);
		stroke: var(--surface);
		stroke-width: 2;
	}
	.markline {
		stroke: var(--grid);
		stroke-dasharray: 3 3;
	}
	.tick {
		fill: var(--text-3);
		font-size: 10.5px;
	}
	.empty {
		fill: var(--text-3);
		font-size: 12px;
	}
	.note {
		font-size: 0.75rem;
		margin: 2px 0 0;
	}
</style>
