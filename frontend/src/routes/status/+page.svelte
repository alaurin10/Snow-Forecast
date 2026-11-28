<script lang="ts">
	import { ago, instant } from '../../lib/time';
	import ErrorNote from '../../lib/components/ErrorNote.svelte';
	import { friendlyError } from '../../lib/errors';
	import { hscroll } from '../../lib/hscroll';
	import { resolve } from '$app/paths';
	import { getStatus } from '../../lib/api';
	import type { StatusOut } from '../../lib/types.gen';

	let status = $state<StatusOut | null>(null);
	let error = $state<string | null>(null);
	let retry = $state(0);
	const KINDS: Record<string, string> = {
		full: 'Scheduled',
		job: 'Refresh',
		rebuild: 'Rebuild',
		manual: 'Manual'
	};

	$effect(() => {
		void retry; // the Try again button runs this again
		error = null;
		getStatus()
			.then((s) => (status = s))
			.catch((e: Error) => (error = friendlyError(e)));
	});

	const NAMES: Record<string, string> = {
		'open-meteo': 'Open-Meteo (weather models)',
		'open-meteo-local': 'Open-Meteo (self-hosted)',
		nws: 'National Weather Service',
		snotel: 'NRCS SNOTEL',
		'bc-asws': 'BC snow pillows',
		'avalanche-us': 'avalanche.org',
		'avalanche-ca': 'Avalanche Canada',
		catalog: 'Ski-area list (OpenSkiMap)'
	};
	// A source is "late" when its last success is older than a day.
	const late = (iso: string | null) => !iso || Date.now() - Date.parse(iso) > 26 * 3600 * 1000;
	// A model run as "27 Nov 00z" (UTC, as runs are named).
	const runName = (iso: string) => {
		const d = new Date(iso);
		const mon = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
		return `${d.getUTCDate()} ${mon} ${String(d.getUTCHours()).padStart(2, '0')}z`;
	};
	const pct = $derived(status ? Math.min(100, (status.weight_today / status.budget) * 100) : 0);
</script>

<svelte:head><title>Status · Snow Watch</title></svelte:head>

<div class="pagehead">
	<a class="back" href={resolve('/settings')}>← Settings</a>
	<h1>Status</h1>
</div>

{#if error}
	<ErrorNote message={error} onretry={() => retry++} />
{:else if !status}
	<p class="loading glass" aria-live="polite">Loading…</p>
{:else}
	<div class="grid">
		<section class="card">
			<h2>{status.local ? 'Public Open-Meteo use today' : 'Open-Meteo usage today'}</h2>
			<div class="bar" role="img" aria-label={`${Math.round(pct)}% of the free daily limit`}>
				<span style:width="{pct}%" class:hot={pct > 80}></span>
			</div>
			<p class="small muted">
				About <strong>{Math.round(status.weight_today).toLocaleString('en-US')}</strong> of
				{status.budget.toLocaleString('en-US')} free calls (UTC day).{status.local
					? " Ensembles, plus any forecasts the server couldn't answer."
					: ''}
			</p>
		</section>

		{#if status.local}
			{@const local = status.local}
			<section class="card" class:bad={!local.ok}>
				<h2>Self-hosted forecasts</h2>
				<p class="small">
					{#if local.ok}<strong>Working</strong>, last answer {ago(local.last_ok_at)}.
					{:else if local.last_error_at}<strong>Not answering</strong>: it last failed
						{ago(local.last_error_at)}.
					{:else}<strong>No requests yet.</strong>{/if}
				</p>
				<p class="small muted">
					{local.requests_today.toLocaleString('en-US')} requests today{#if local.latency_s !== null},
						{local.latency_s.toFixed(1)} s each on average{/if}.
					{#if local.fallbacks_today}{local.fallbacks_today.toLocaleString('en-US')} went to the public
						API instead.{:else}None went to the public API instead.{/if}
				</p>
				{#if !local.ok && local.last_error}
					<p class="small err-line">{local.last_error}</p>
				{/if}
			</section>
		{/if}

		{#if status.ensembles}
			{@const ens = status.ensembles}
			{@const publicNow = ens.systems.filter(
				(s) => ens.mode === 'local' && s.source !== 'self-hosted'
			)}
			<section class="card">
				<h2>Ensembles</h2>
				<p class="small">
					{#if ens.mode === 'local'}From the self-hosted server while its downloaded run is fresh,
						otherwise from the public API.
					{:else if ens.mode === 'shadow'}From the public API; each run also asks the self-hosted
						server and compares.
					{:else}From the public API.{/if}
				</p>
				<div class="table-wrap" use:hscroll>
					<table class="data">
						<thead>
							<tr><th>System</th><th>From</th><th>Run, age</th></tr>
						</thead>
						<tbody>
							{#each ens.systems as s (s.system)}
								<tr class:bad={publicNow.includes(s)}>
									<th scope="row">{s.label}</th>
									<td>{s.source === 'self-hosted' ? 'Self-hosted' : 'Public API'}</td>
									<td class="age"
										>{s.run ? `${runName(s.run)}, ${Math.round(s.age_h ?? 0)} h` : '–'}</td
									>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#each publicNow as s (s.system)}
					<p class="small err-line">
						<strong class="warn">{s.label}</strong>: public API{s.since
							? `, since ${ago(s.since)}`
							: ''}{s.reason ? ` (${s.reason})` : ''}.
					</p>
				{/each}
				{#if ens.shadow.length}
					<h3 class="sub">Compared with the public API, last 7 days</h3>
					<div class="table-wrap" use:hscroll>
						<table class="data">
							<thead>
								<tr><th>System</th><th>Same run</th><th>Members</th><th>Diff, cm</th></tr>
							</thead>
							<tbody>
								{#each ens.shadow as r (r.system)}
									<tr>
										<th scope="row">{r.label}</th>
										<td class="num"
											>{r.same_run} of {r.comparisons}{r.errors ? ` (${r.errors} failed)` : ''}</td
										>
										<td class="num">{r.members_local_min ?? '–'} / {r.members_public_max ?? '–'}</td
										>
										<td class="num"
											>{r.mean_diff_cm === null
												? '–'
												: `${r.mean_diff_cm.toFixed(1)} / ${(r.max_diff_cm ?? 0).toFixed(1)}`}</td
										>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
					<p class="small muted">
						Same run: comparisons where both had the same model run; only those count towards the
						differences. Members: the fewest the server gave / the most the public API gave. Diff:
						how much members' 16-day snowfall differed, mean / largest.
					</p>
					{@const behind = Math.max(0, ...ens.shadow.map((r) => r.reach_gap_h ?? 0))}
					{#if behind > 0}
						<p class="small muted">
							The server's forecasts reached up to {behind} h less far ahead than the public API's.
						</p>
					{/if}
				{/if}
			</section>
		{/if}

		{#if status.model_runs?.length}
			<section class="card">
				<h2>Model runs</h2>
				<p class="muted small">
					{status.refresh === 'data'
						? 'Each location is refreshed a few minutes after a model it uses has a new run (at most every 40 minutes, at least every 3 hours).'
						: 'Forecasts are refreshed on a fixed schedule; the newest run of each model:'}
				</p>
				<div class="table-wrap" use:hscroll>
					<table class="data">
						<thead><tr><th>Model</th><th>Run</th><th>Available</th></tr></thead>
						<tbody>
							{#each status.model_runs ?? [] as m (m.model)}
								<tr>
									<th scope="row">{m.label}</th>
									<td>{m.init_time ? `${runName(m.init_time)}` : '–'}</td>
									<td class="age">{ago(m.available_at)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		{/if}

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
									<th scope="row"
										>{NAMES[s.source] ?? s.source}{#if late(s.last_ok_at)}<span class="sr-only">
												(no success for a day)</span
											>{/if}</th
									>
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
						{:else}
							<tr><td colspan="4" class="muted">No locations yet.</td></tr>
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
								<td>{instant(r.started_at)}</td>
								<td>{KINDS[r.kind] ?? r.kind}</td>
								<td>{r.status}</td>
								<td title={r.errors.join('\n')}>{r.errors.length}</td>
								<td class="num">{Math.round(r.api_weight)}</td>
							</tr>
						{:else}
							<tr><td colspan="5" class="muted">No runs yet.</td></tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	</div>
{/if}

<style>
	.back {
		display: inline-block;
		margin-bottom: 6px;
		text-decoration: none;
		font-size: 0.85rem;
		font-weight: 500;
		color: var(--text-2);
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
	.bad td,
	.card.bad strong {
		color: var(--temp);
	}
	.sub {
		margin: 16px 0 8px;
		font-size: 1rem;
	}
	.warn {
		color: var(--temp);
	}
	.err-line {
		overflow-wrap: anywhere;
		font-size: 0.8rem;
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
