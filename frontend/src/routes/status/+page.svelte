<script lang="ts">
	import { hscroll } from '../../lib/hscroll';
	import { resolve } from '$app/paths';
	import { getStatus } from '../../lib/api';
	import type { StatusOut } from '../../lib/types.gen';

	let status = $state<StatusOut | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		getStatus()
			.then((s) => (status = s))
			.catch((e: Error) => (error = e.message));
	});

	const ago = (iso: string | null | undefined): string => {
		if (!iso) return 'never';
		const m = Math.round((Date.now() - Date.parse(iso)) / 60000);
		if (m < 60) return `${Math.max(0, m)} min ago`;
		const h = Math.round(m / 60);
		return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`;
	};
	const when = (iso: string) =>
		new Date(iso).toLocaleString('en-US', {
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		});
	const NAMES: Record<string, string> = {
		'open-meteo': 'Open-Meteo (weather models)',
		nws: 'National Weather Service',
		snotel: 'NRCS SNOTEL',
		'bc-asws': 'BC snow pillows',
		'avalanche-us': 'avalanche.org',
		'avalanche-ca': 'Avalanche Canada',
		catalog: 'Ski-area catalog'
	};
	// A source is "late" when its last success is older than a day.
	const late = (iso: string | null) => !iso || Date.now() - Date.parse(iso) > 26 * 3600 * 1000;
	const pct = $derived(status ? Math.min(100, (status.weight_today / status.budget) * 100) : 0);
</script>

<svelte:head><title>Status · Snow Watch</title></svelte:head>

<div class="head">
	<a class="faint back" href={resolve('/more')}>← More</a>
	<h1>Status</h1>
</div>

{#if error}
	<p class="card">Can't load the status: {error}</p>
{:else if !status}
	<p class="muted">Loading…</p>
{:else}
	<div class="grid">
		<section class="card">
			<h2>Open-Meteo usage today</h2>
			<div class="bar" role="img" aria-label={`${Math.round(pct)}% of the free daily limit`}>
				<span style:width="{pct}%" class:hot={pct > 80}></span>
			</div>
			<p class="small muted">
				About <strong>{Math.round(status.weight_today).toLocaleString('en-US')}</strong> of
				{status.budget.toLocaleString('en-US')} free calls (UTC day).
			</p>
		</section>

		<section class="card">
			<h2>Sources</h2>
			{#if status.sources.length}
				<div class="table-wrap" use:hscroll>
					<table class="data">
						<thead>
							<tr><th>Source</th><th>Last success</th><th>Calls today</th><th>Last error</th></tr>
						</thead>
						<tbody>
							{#each status.sources as s (s.source)}
								<tr class:bad={late(s.last_ok_at)}>
									<th scope="row">{NAMES[s.source] ?? s.source}</th>
									<td>{ago(s.last_ok_at)}</td>
									<td class="num"
										>{s.calls_today}{s.errors_today ? ` (${s.errors_today} failed)` : ''}</td
									>
									<td class="err" title={s.last_error ?? ''}
										>{s.last_error ? `${ago(s.last_error_at)}: ${s.last_error}` : '–'}</td
									>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<p class="muted small">No source has been called yet.</p>
			{/if}
		</section>

		<section class="card">
			<h2>Locations</h2>
			<div class="table-wrap" use:hscroll>
				<table class="data">
					<thead>
						<tr><th>Location</th><th>Forecast</th><th>Station</th><th>Flags</th></tr>
					</thead>
					<tbody>
						{#each status.locations as l (l.id)}
							<tr>
								<th scope="row"><a href={resolve('/location/[id]', { id: l.id })}>{l.name}</a></th>
								<td class="age">{ago(l.generated_at)}</td>
								<td class="age">{l.station ? ago(l.station_obs_time) : '–'}</td>
								<td class="num">{l.flags}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>

		<section class="card">
			<h2>Recent runs</h2>
			<div class="table-wrap" use:hscroll>
				<table class="data">
					<thead>
						<tr><th>Started</th><th>Kind</th><th>Status</th><th>Errors</th><th>Calls</th></tr>
					</thead>
					<tbody>
						{#each status.runs as r (r.id)}
							<tr class:bad={r.status === 'failed'}>
								<td>{when(r.started_at)}</td>
								<td>{r.kind}</td>
								<td>{r.status}</td>
								<td title={r.errors.join('\n')}>{r.errors.length}</td>
								<td class="num">{Math.round(r.api_weight)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	</div>
{/if}

<style>
	.head h1 {
		font-size: 1.3rem;
		margin: 2px 0 10px;
	}
	.back {
		font-size: 0.8rem;
		text-decoration: none;
	}
	.grid {
		display: grid;
		gap: 12px;
	}
	@media (min-width: 1100px) {
		.grid {
			grid-template-columns: 1fr 1fr;
			align-items: start;
		}
	}
	h2 {
		margin: 0 0 8px;
	}
	.small {
		font-size: 0.85rem;
	}
	.bar {
		height: 10px;
		border-radius: 999px;
		background: var(--surface-2);
		overflow: hidden;
		border: 1px solid var(--border);
	}
	.bar span {
		display: block;
		height: 100%;
		background: var(--snow);
	}
	.bar span.hot {
		background: var(--temp);
	}
	.bad th,
	.bad td {
		color: var(--temp);
	}
	.err {
		max-width: 260px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.8rem;
	}
	.age {
		white-space: nowrap;
		font-size: 0.82rem;
	}
	th a {
		color: var(--text);
	}
</style>
