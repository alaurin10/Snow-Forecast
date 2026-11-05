<script lang="ts">
	import { resolve } from '$app/paths';
	import { getLocations } from '../lib/api';
	import { prefs } from '../lib/prefs.svelte';
	import { snowNum, converters } from '../lib/units';
	import type { LocationSummary } from '../lib/types.gen';

	let items = $state<LocationSummary[] | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		getLocations()
			.then((l) => (items = l))
			.catch((e: Error) => (error = e.message));
	});

	const c = $derived(converters(prefs.units));
</script>

<svelte:head><title>Snow Watch</title></svelte:head>

<h1 class="title">Locations</h1>
{#if error}
	<p class="card">Can't load locations: {error}</p>
{:else if !items}
	<p class="muted">Loading…</p>
{:else}
	<ul class="grid">
		{#each items as l (l.id)}
			<li>
				<a class="card loc" href={resolve('/location/[id]', { id: l.id })}>
					<div class="name">
						<strong>{l.name}</strong>
						<span class="muted"
							>{l.region} · {l.kind === 'backcountry' ? 'Backcountry' : 'Resort'}</span
						>
					</div>
					{#if l.run_id === null}
						<div class="faint">No forecast yet</div>
					{:else}
						<div class="nums">
							<div>
								<span class="big num">{snowNum(l.next5_cm, prefs.units)}</span>
								<span class="unit">{c.snowUnit}</span>
								<div class="faint small">
									{`next 5 days${
										l.next5_p10_cm !== null && l.next5_p90_cm !== null
											? ` · ${snowNum(l.next5_p10_cm, prefs.units)}–${snowNum(l.next5_p90_cm, prefs.units)}`
											: ''
									}`}
								</div>
							</div>
							<div>
								<span class="mid num">{snowNum(l.d6_10_cm, prefs.units)}</span>
								<span class="unit">{c.snowUnit}</span>
								<div class="faint small">days 6–10</div>
							</div>
						</div>
						{#if l.alerts}<div class="alert">
								{l.alerts} NWS alert{l.alerts > 1 ? 's' : ''}
							</div>{/if}
					{/if}
				</a>
			</li>
		{/each}
	</ul>
{/if}

<style>
	.title {
		font-size: 1.3rem;
		margin: 6px 0 12px;
	}
	.grid {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		gap: 12px;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
	}
	.loc {
		display: grid;
		gap: 10px;
		color: inherit;
		text-decoration: none;
	}
	.loc:hover {
		border-color: var(--snow);
	}
	.name {
		display: grid;
	}
	.name .muted {
		font-size: 0.82rem;
	}
	.nums {
		display: flex;
		gap: 28px;
		align-items: flex-end;
	}
	.big {
		font-size: 2.2rem;
		font-weight: 600;
		line-height: 1;
	}
	.mid {
		font-size: 1.4rem;
		font-weight: 600;
	}
	.unit {
		color: var(--text-2);
		margin-left: 2px;
	}
	.small {
		font-size: 0.78rem;
	}
	.alert {
		font-size: 0.8rem;
		color: var(--text);
		background: var(--surface-2);
		border-radius: 6px;
		padding: 3px 8px;
		justify-self: start;
	}
</style>
