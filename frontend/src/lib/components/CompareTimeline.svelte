<!-- Compare: the timeline under the chart, as on a location's forecast. One column per
     forecast day, each with a small bar of the day's snow for every location drawn as a
     line (in its line's colour), and the chart's window raised across the days it shows.
     Drag it, tap a day (the window centres on it), or step a day with ‹ ›. -->
<script module lang="ts">
	export interface TimelineDay {
		date: string;
		/** "Today", "Thu" … */
		label: string;
		/** "Tod", "Th" … for phones. */
		short: string;
		/** The day's snow (cm) for each drawn location, in colour order. */
		bars: { id: string; name: string; slot: number; cm: number }[];
	}
</script>

<script lang="ts">
	import { viewport } from '../viewport.svelte';
	import { snow, type UnitSystem } from '../units';

	interface Props {
		days: TimelineDay[];
		/** The window, in days from the left edge (fractions allowed). */
		span: { from: number; to: number };
		/** The days the window touches (indexes). */
		inView: { from: number; to: number };
		/** The window is every day: nothing to move. */
		whole: boolean;
		canPrev: boolean;
		canNext: boolean;
		range: number;
		units: UnitSystem;
		/** Centre the window on day `k`. */
		onday: (k: number) => void;
		onstep: (by: -1 | 1) => void;
		/** Back to today. */
		onhome: () => void;
	}

	let { days, span, inView, whole, canPrev, canNext, range, units, onday, onstep, onhome }: Props =
		$props();

	const phone = $derived(viewport.phone);
	const n = $derived(Math.max(1, days.length));
	// One scale for every bar, at least an inch, so a dusting stays small.
	const max = $derived(Math.max(2.54, ...days.flatMap((d) => d.bars.map((b) => b.cm))));
	const BAR = $derived(phone ? 22 : 28);
	const h = (cm: number) => (cm < 0.25 ? 0 : Math.max(3, (cm / max) * BAR));
	const note = $derived(
		whole
			? `Showing all ${days.length} days`
			: range === 1
				? 'Drag or tap a day to read it hour by hour'
				: 'Drag the window or tap a day; ‹ › move one day'
	);
	const describe = (d: TimelineDay) =>
		d.bars.length
			? `${d.label}: ${d.bars.map((b) => `${b.name} ${snow(b.cm, units)}`).join(', ')}`
			: d.label;

	let down = false;
	const dayAt = (e: PointerEvent) => {
		const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
		return Math.max(0, Math.min(n - 1, Math.floor(((e.clientX - r.left) / r.width) * n)));
	};
	function key(e: KeyboardEvent) {
		if (whole) return;
		if (e.key === 'ArrowRight' && canNext) onstep(1);
		else if (e.key === 'ArrowLeft' && canPrev) onstep(-1);
		else if (e.key === 'Home') onhome();
		else return;
		e.preventDefault();
	}
</script>

<div class="ct" class:phone>
	<div class="tl">
		<button
			class="step"
			aria-label="One day earlier"
			disabled={whole || !canPrev}
			onclick={() => onstep(-1)}
		>
			<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
				><path d="M15 5l-7 7 7 7" /></svg
			>
		</button>
		<div
			class="track"
			class:whole
			role="slider"
			tabindex={whole ? -1 : 0}
			aria-label="Days the chart shows"
			aria-valuemin={0}
			aria-valuemax={n - 1}
			aria-valuenow={inView.from}
			aria-valuetext={days.length
				? `${days[inView.from]?.label ?? ''} to ${days[inView.to]?.label ?? ''}`
				: ''}
			onpointerdown={(e) => {
				if (whole) return;
				down = true;
				(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
				onday(dayAt(e));
			}}
			onpointermove={(e) => down && onday(dayAt(e))}
			onpointerup={() => (down = false)}
			onpointercancel={() => (down = false)}
			onkeydown={key}
			style:--n={n}
		>
			<span
				class="win"
				style:left="{((span.from / n) * 100).toFixed(2)}%"
				style:width="{(((span.to - span.from) / n) * 100).toFixed(2)}%"
			></span>
			{#each days as d, k (d.date)}
				<span
					class="day"
					class:in={whole || (k >= inView.from && k <= inView.to)}
					title={describe(d)}
				>
					<span class="bars" style:height="{BAR}px">
						{#each d.bars as b (b.id)}<i class="s{b.slot}" style:height="{h(b.cm)}px"></i>{/each}
					</span>
					<small>{phone ? d.short : d.label}</small>
				</span>
			{/each}
		</div>
		<button
			class="step"
			aria-label="One day later"
			disabled={whole || !canNext}
			onclick={() => onstep(1)}
		>
			<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
				><path d="M9 5l7 7-7 7" /></svg
			>
		</button>
	</div>
	<p class="note">{note} <span class="faint">· bars: each line’s snow by day</span></p>
</div>

<style>
	.ct {
		display: grid;
		gap: 6px;
		min-width: 0;
	}
	.tl {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.step {
		flex: 0 0 36px;
		height: 56px;
		border: 0;
		border-radius: 14px;
		background: var(--surface-2);
		color: var(--text-2);
		display: grid;
		place-items: center;
		cursor: pointer;
		transition:
			background-color var(--ease),
			transform 200ms cubic-bezier(0.3, 1.6, 0.5, 1);
	}
	.step:active {
		transform: scale(0.94);
	}
	.step:disabled {
		opacity: 0.35;
		cursor: default;
	}
	.step svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 2.1;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.track {
		position: relative;
		flex: 1;
		min-width: 0;
		height: 60px;
		border-radius: 16px;
		background: var(--surface-2);
		display: grid;
		grid-template-columns: repeat(var(--n), minmax(0, 1fr));
		touch-action: none;
		cursor: grab;
		user-select: none;
	}
	.track.whole {
		cursor: default;
	}
	.win {
		position: absolute;
		top: 3px;
		bottom: 3px;
		border-radius: 13px;
		background: var(--sel);
		box-shadow: var(--sel-shadow);
		transition:
			left var(--spring),
			width var(--spring);
		pointer-events: none;
	}
	.day {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: flex-end;
		gap: 3px;
		padding: 0 2px 6px;
		min-width: 0;
		pointer-events: none;
	}
	.bars {
		display: flex;
		align-items: flex-end;
		justify-content: center;
		gap: 2px;
		max-width: 100%;
	}
	.bars i {
		flex: 0 1 8px;
		min-width: 4px;
		border-radius: 2px 2px 0 0;
		background: var(--k);
		opacity: 0.4;
		transition: opacity var(--ease);
	}
	.day.in .bars i {
		opacity: 1;
	}
	.s0 {
		--k: var(--cmp1);
	}
	.s1 {
		--k: var(--cmp2);
	}
	.s2 {
		--k: var(--cmp3);
	}
	.s3 {
		--k: var(--cmp4);
	}
	.day small {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
	}
	.day.in small {
		color: var(--text);
	}
	.phone .step {
		flex-basis: 30px;
		height: 50px;
	}
	.phone .track {
		height: 52px;
	}
	.phone .day small {
		font-size: 0.68rem;
	}
	.note {
		margin: 0;
		text-align: center;
		font-size: 0.75rem;
		color: var(--text-3);
	}
	.phone .note .faint {
		display: none;
	}
</style>
