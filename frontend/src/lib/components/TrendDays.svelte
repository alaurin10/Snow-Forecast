<!-- How each of the next few days changed over the last few runs (consensus, mid band). -->
<script lang="ts">
	import { hscroll } from '../hscroll';
	import type { TrendRun } from '../types.gen';
	import { snowNum, type UnitSystem } from '../units';
	import { weekday } from '../time';

	interface Props {
		runs: TrendRun[];
		units: UnitSystem;
		days?: number;
		count?: number;
	}

	let { runs, units, days = 5, count = 5 }: Props = $props();
	const recent = $derived(runs.slice(-count));
	const dates = $derived(
		Object.keys(recent.at(-1)?.daily ?? {})
			.sort()
			.slice(0, days)
	);
	const when = (iso: string) =>
		new Date(iso).toLocaleString('en-US', { weekday: 'short', hour: 'numeric' });
	const delta = (date: string) => {
		const vals = recent
			.map((r) => r.daily[date])
			.filter((v): v is number => v !== null && v !== undefined);
		return vals.length >= 2 ? vals.at(-1)! - vals[0] : null;
	};
</script>

{#if recent.length >= 2 && dates.length}
	<h2>How each day changed</h2>
	<div class="table-wrap" use:hscroll>
		<table class="data">
			<thead>
				<tr>
					<th>Run</th>
					{#each dates as d (d)}<th>{weekday(d)}</th>{/each}
				</tr>
			</thead>
			<tbody>
				{#each recent as r (r.run_id)}
					<tr>
						<th scope="row">{when(r.issued_at)}</th>
						{#each dates as d (d)}<td class="num">{snowNum(r.daily[d] ?? null, units)}</td>{/each}
					</tr>
				{/each}
				<tr class="change">
					<th scope="row">Change</th>
					{#each dates as d (d)}
						{@const c = delta(d)}
						<td class="num">{c === null ? '–' : `${c > 0 ? '+' : ''}${snowNum(c, units)}`}</td>
					{/each}
				</tr>
			</tbody>
		</table>
	</div>
{/if}

<style>
	h2 {
		margin: 12px 0 6px;
		font-size: 0.95rem;
	}
	.change th,
	.change td {
		font-weight: 600;
	}
</style>
