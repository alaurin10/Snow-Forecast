<!-- One day, hour by hour, in a popup over the day list: the forecast chart at its hourly
     step with its metric chips, so the list stays where you left it underneath. -->
<script lang="ts">
	import type { BandOut } from '../types.gen';
	import type { UnitSystem } from '../units';
	import { monthDay, weekday } from '../time';
	import ForecastChart from './ForecastChart.svelte';
	import Sheet from '../components/Sheet.svelte';

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

<Sheet
	title="{weekday(date)} {monthDay(date)}, hour by hour"
	sub={band.label}
	width={780}
	{onclose}
>
	<ForecastChart {band} {bands} {units} range={1} {start} embedded />
</Sheet>
