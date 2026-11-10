<!-- One day, hour by hour, in a popup over the day list: the forecast chart at its hourly
     step with its metric chips, so the list stays where you left it underneath. -->
<script lang="ts">
	import { modal } from '../modal';
	import type { BandOut } from '../types.gen';
	import type { UnitSystem } from '../units';
	import { monthDay, weekday } from '../time';
	import ForecastChart from './ForecastChart.svelte';

	interface Props {
		band: BandOut;
		bands: BandOut[];
		units: UnitSystem;
		date: string;
		/** The day's first hour (a local ISO time). */
		start: string;
		onclose: () => void;
	}

	let { band, bands, units, date, start, onclose }: Props = $props();
</script>

<div class="modal" use:modal={{ onclose }}>
	<div class="scrim" role="presentation" onclick={onclose}></div>
	<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="day-title" tabindex="-1">
		<header>
			<div>
				<h3 id="day-title">{weekday(date)} {monthDay(date)}, hour by hour</h3>
				<div class="faint">{band.label}</div>
			</div>
			<button class="close" onclick={onclose} aria-label="Close">✕</button>
		</header>
		<ForecastChart {band} {bands} {units} range={1} {start} embedded />
	</div>
</div>

<style>
	.modal {
		display: contents;
	}
	.scrim {
		position: fixed;
		inset: 0;
		background: rgb(0 0 0 / 0.45);
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
		border: 1px solid var(--border);
		border-radius: 20px 20px 0 0;
		box-shadow: 0 -8px 30px rgb(0 0 0 / 0.3);
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
		font-size: 1.1rem;
		font-weight: 600;
	}
	.faint {
		font-size: 0.8rem;
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
	@media (min-width: 641px) {
		.sheet {
			left: 50%;
			right: auto;
			width: 600px;
			transform: translateX(-50%);
		}
	}
</style>
