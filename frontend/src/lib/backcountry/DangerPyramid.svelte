<!--
  The avalanche center's danger rating, exactly as published: today and tomorrow
  by elevation (alpine on top), the problems and the bottom line, with a
  prominent link to the full forecast. Expired forecasts show as Expired, never
  as current; the API applies the expiry against the clock.
-->
<script lang="ts">
	import type { AvalancheView } from '../types.gen';
	import { dangerWord } from '../conditions';
	import { weekday } from '../time';

	interface Props {
		view: AvalancheView | null;
		/** The location's timezone, for issue and expiry times. */
		tz: string;
		/** Today's date at the location (YYYY-MM-DD). */
		today: string;
		/** One line for the top of the Forecast tab instead of the full card. */
		compact?: boolean;
	}

	let { view, tz, today, compact = false }: Props = $props();

	const doc = $derived(view?.doc ?? null);
	const status = $derived(view?.status ?? 'none');
	const center = $derived(
		doc?.center_id && doc.center_id !== 'avcan' ? doc.center_id : doc?.center
	);
	const TIERS = [
		{ key: 'alpine', name: 'Alpine', width: 62 },
		{ key: 'treeline', name: 'Treeline', width: 81 },
		{ key: 'below', name: 'Below treeline', width: 100 }
	] as const;

	function when(iso: string | null | undefined): string {
		if (!iso) return '–';
		return new Date(iso).toLocaleString('en-US', {
			timeZone: tz,
			weekday: 'short',
			hour: 'numeric',
			minute: '2-digit'
		});
	}
	const dayName = (date: string) => (date === today ? 'Today' : weekday(date));
	const todayDay = $derived(
		(doc?.days ?? []).find((d) => d.date === today) ?? doc?.days?.[0] ?? null
	);
</script>

{#if compact}
	<div class="strip" aria-label="Avalanche danger">
		<span class="lead">Avalanche</span>
		{#if status === 'current' && todayDay}
			<span class="faint">{dayName(todayDay.date)}</span>
			{#each TIERS as t (t.key)}
				{@const lvl = todayDay[t.key]}
				<span class="danger d{lvl ?? 0}" title={`${t.name}: ${lvl ?? '–'} ${dangerWord(lvl)}`}
					>{t.name.split(' ')[0]} {lvl ?? '–'}{lvl ? ` · ${dangerWord(lvl)}` : ''}</span
				>
			{/each}
		{:else if status === 'expired'}
			<span class="danger d0">Expired</span>
		{:else if status === 'no_rating'}
			<span class="danger d0">No rating</span>
		{:else}
			<span class="danger d0">No zone</span>
		{/if}
		{#if doc?.link}
			<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
			<a href={doc.link} target="_blank" rel="noopener">{center ?? 'Forecast'} ↗</a>
		{/if}
	</div>
{:else}
	<div class="avy">
		<header>
			<h2>Avalanche danger</h2>
			{#if doc}
				<div class="muted small">
					{doc.center}{doc.zone ? ` · ${doc.zone}` : ''}
				</div>
			{/if}
		</header>

		{#if status === 'current' && doc}
			<div class="days">
				{#each doc.days ?? [] as d (d.date)}
					<figure class="pyramid">
						<figcaption>{dayName(d.date)}</figcaption>
						{#each TIERS as t (t.key)}
							{@const lvl = d[t.key]}
							<div class="tier">
								<span class="tname">{t.name}</span>
								<span class="bar danger d{lvl ?? 0}" style="width: {t.width}%"
									>{lvl ?? '–'} · {dangerWord(lvl)}</span
								>
							</div>
						{/each}
					</figure>
				{/each}
			</div>
			{#if doc.problems?.length}
				<h3>Avalanche problems</h3>
				<ul class="problems">
					{#each doc.problems ?? [] as p, i (i)}
						<li>
							<strong>{p.name}</strong>
							<span class="muted">
								{[
									p.likelihood,
									p.size ? `size ${p.size}` : null,
									p.aspects?.length ? p.aspects.join(' ') : null,
									p.elevations?.length ? p.elevations.join(', ') : null
								]
									.filter(Boolean)
									.join(' · ')}
							</span>
						</li>
					{/each}
				</ul>
			{/if}
			{#if doc.summary}
				<blockquote class="summary">{doc.summary}</blockquote>
			{/if}
			<p class="faint small">
				Issued {when(doc.issued_at)} · expires {when(doc.expires_at)}. Shown as published by {doc.center}.
			</p>
		{:else if status === 'expired' && doc}
			<p class="state"><span class="danger d0">Expired</span></p>
			<p class="muted small">
				The last forecast expired {when(doc.expires_at)}. Check {doc.center} for the current one.
			</p>
		{:else if status === 'no_rating' && doc}
			<p class="state"><span class="danger d0">No rating</span></p>
			<p class="muted small">
				{doc.center} has no danger rating for this zone right now{doc.off_season
					? ' (outside its forecast season)'
					: ''}. Conditions can still be dangerous wherever there is enough snow to slide.
			</p>
			{#if doc.summary}<blockquote class="summary">{doc.summary}</blockquote>{/if}
		{:else}
			<p class="muted small">No avalanche forecast zone is set for this location.</p>
		{/if}

		{#if doc?.link}
			<!-- External site: resolve() is only for routes in this app. -->
			<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
			<a class="btn primary full" href={doc.link} target="_blank" rel="noopener"
				>Full forecast at {center} ↗</a
			>
		{/if}
	</div>
{/if}

<style>
	.avy header {
		margin-bottom: 8px;
	}
	h2 {
		margin: 0;
	}
	h3 {
		font-size: 0.85rem;
		margin: 12px 0 4px;
	}
	.small {
		font-size: 0.85rem;
	}
	.days {
		display: grid;
		gap: 14px;
		grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
	}
	.pyramid {
		margin: 0;
		display: grid;
		gap: 4px;
	}
	figcaption {
		font-weight: 600;
		font-size: 0.85rem;
	}
	.tier {
		display: grid;
		grid-template-columns: 96px 1fr;
		align-items: center;
		gap: 8px;
		font-size: 0.8rem;
	}
	.tname {
		color: var(--text-2);
	}
	.bar {
		justify-content: center;
		border-radius: 6px;
		padding: 4px 6px;
		margin: 0 auto;
		box-sizing: border-box;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.problems {
		margin: 0;
		padding-left: 18px;
		font-size: 0.85rem;
		display: grid;
		gap: 3px;
	}
	.summary {
		margin: 10px 0 6px;
		padding: 6px 10px;
		border-left: 3px solid var(--border);
		font-size: 0.88rem;
		white-space: pre-line;
		color: var(--text);
	}
	.state {
		margin: 6px 0;
	}
	.full {
		display: block;
		text-align: center;
		margin-top: 10px;
		text-decoration: none;
	}
	.strip {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		font-size: 0.85rem;
	}
	.lead {
		font-weight: 600;
	}
	.strip a {
		color: var(--text-2);
		margin-left: auto;
	}
</style>
