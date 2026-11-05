<script lang="ts">
	import type { BandOut } from '../types.gen';
	import { converters, elevation, type UnitSystem } from '../units';

	let { bands, units }: { bands: BandOut[]; units: UnitSystem } = $props();
	const c = $derived(converters(units));
	const f = (v: number | null, d = 0) => (v === null ? '–' : v.toFixed(d));
</script>

<div class="table-wrap">
	<table class="data">
		<thead>
			<tr>
				<th>Elevation</th>
				<th>Now</th>
				<th>24 h lo/hi</th>
				<th>Last 24 h</th>
				<th>Next 24 h</th>
				<th>Next 5 days</th>
				<th>Days 6–10</th>
			</tr>
		</thead>
		<tbody>
			{#each [...bands].reverse() as b (b.band)}
				<tr>
					<td>{b.label} <span class="faint">{elevation(b.elev_m, units)}</span></td>
					<td>{f(c.temp(b.stats.temp_now_c))}{c.tempUnit}</td>
					<td>{f(c.temp(b.stats.tmin24_c))}° / {f(c.temp(b.stats.tmax24_c))}°</td>
					<td>{f(c.snow(b.stats.last24_cm), c.snowDigits)} {c.snowUnit}</td>
					<td>{f(c.snow(b.stats.next24_cm), c.snowDigits)} {c.snowUnit}</td>
					<td><strong>{f(c.snow(b.stats.next5_cm), c.snowDigits)} {c.snowUnit}</strong></td>
					<td>{f(c.snow(b.stats.d6_10_cm), c.snowDigits)} {c.snowUnit}</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>
