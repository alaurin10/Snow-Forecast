<script lang="ts">
	import { hscroll } from '../hscroll';
	import type { PeriodOut } from '../types.gen';
	import { converters, type UnitSystem } from '../units';

	let { periods, units }: { periods: PeriodOut[]; units: UnitSystem } = $props();
	const c = $derived(converters(units));
	const f = (v: number | null, d = 0) => (v === null ? '–' : v.toFixed(d));
</script>

<div class="table-wrap" use:hscroll>
	<table class="data">
		<thead>
			<tr>
				<th>Period</th>
				<th>Snow {c.snowUnit}</th>
				<th>10–90%</th>
				<th>Water {c.waterUnit}</th>
				<th>Type</th>
				<th>Quality</th>
				<th>Hi / Lo</th>
				<th>Snow lvl {c.heightUnit}</th>
				<th>Gust {c.speedUnit}</th>
				<th>Cloud</th>
				<th>Basis</th>
			</tr>
		</thead>
		<tbody>
			{#each periods as p (p.key)}
				<tr class:night={p.kind === 'night'}>
					<td>{p.label}</td>
					<td><strong>{f(c.snow(p.snow_cm), c.snowDigits)}</strong></td>
					<td
						>{p.ens
							? `${f(c.snow(p.ens.p10), c.snowDigits)}–${f(c.snow(p.ens.p90), c.snowDigits)}`
							: '–'}</td
					>
					<td>{f(c.water(p.water_mm), c.waterDigits)}</td>
					<td>{p.ptype}</td>
					<td>{p.quality ?? '–'}</td>
					<td>{f(c.temp(p.tmax_c))}° / {f(c.temp(p.tmin_c))}°</td>
					<td
						>{p.snow_level_min_m === null
							? '–'
							: (Math.round((c.height(p.snow_level_min_m) ?? 0) / 100) * 100).toLocaleString(
									'en-US'
								)}</td
					>
					<td>{f(c.speed(p.gust_max_kmh))}</td>
					<td>{p.cloud_mean ?? '–'}%</td>
					<td class="faint">{p.basis === 'ensemble' ? 'ensemble' : `${p.nmodels} models`}</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	tr.night td {
		background: var(--surface-2);
	}
	tr.night td:first-child {
		background: var(--surface-2);
	}
</style>
