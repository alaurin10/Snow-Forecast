<!--
  Chance of at least each amount: the share of ensemble members that reach it, for the
  next five days and for days 6–10, as bars. Replaces two step curves that needed
  reading off an axis.
-->
<script lang="ts">
	import { converters, type UnitSystem } from '../units';

	interface Props {
		/** Member totals in cm for each window (any order); empty when there are none. */
		next5: number[];
		d6_10: number[];
		units: UnitSystem;
		/** The members are scaled from the mid-mountain ensemble. */
		estimated?: boolean;
	}

	let { next5, d6_10, units, estimated = false }: Props = $props();
	const c = $derived(converters(units));
	// Round amounts in each unit system: 1 in to 2 ft, or 2 cm to 60 cm.
	const steps = $derived(units === 'imperial' ? [1, 3, 6, 12, 18, 24] : [2, 5, 15, 30, 45, 60]);
	const share = (members: number[], t: number) => {
		if (!members.length) return null;
		const vals = members.map((v) => c.snow(v) ?? 0);
		return Math.round((100 * vals.filter((v) => v >= t).length) / vals.length);
	};
	const cols = $derived([
		{ name: 'Next 5 days', members: next5 },
		{ name: 'Days 6–10', members: d6_10 }
	]);
	const none = $derived(!next5.length && !d6_10.length);
</script>

<div class="ladder">
	<h2>Chance of at least…</h2>
	{#if none}
		<p class="muted small">No ensemble data in this run.</p>
	{:else}
		<table>
			<thead>
				<tr>
					<th scope="col"><span class="sr-only">Amount</span></th>
					{#each cols as col (col.name)}<th scope="col">{col.name}</th>{/each}
				</tr>
			</thead>
			<tbody>
				{#each steps as t (t)}
					<tr>
						<th scope="row" class="num">{t} {c.snowUnit}</th>
						{#each cols as col (col.name)}
							{@const p = share(col.members, t)}
							<td>
								{#if p === null}
									<span class="faint">–</span>
								{:else}
									<span class="bar" aria-hidden="true"><i style:width="{p}%"></i></span>
									<span class="pct num">{p}%</span>
								{/if}
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
		<p class="faint small">
			The share of ensemble members with at least that much{estimated
				? ', estimated from the mid-mountain ensemble'
				: ''}.
		</p>
	{/if}
</div>

<style>
	h2 {
		margin: 0 0 8px;
	}
	.small {
		font-size: 0.82rem;
		margin: 8px 0 0;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.86rem;
	}
	thead th {
		padding: 0 0 6px 10px;
		text-align: left;
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--text-2);
	}
	tbody th {
		width: 1%;
		padding: 5px 4px 5px 0;
		text-align: right;
		font-weight: 600;
		white-space: nowrap;
	}
	td {
		padding: 5px 0 5px 10px;
		white-space: nowrap;
	}
	td > * {
		vertical-align: middle;
	}
	.bar {
		display: inline-block;
		width: calc(100% - 3.4em);
		height: 12px;
		border-radius: 6px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.bar i {
		display: block;
		height: 100%;
		border-radius: 6px;
		background: var(--snow);
	}
	.pct {
		display: inline-block;
		width: 3em;
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
</style>
