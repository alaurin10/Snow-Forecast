<!--
  One snow station, tapped on the map (the map panel's content; its name is the panel's
  title): snow depth now, the change over 24 hours, and the week's daily depths as a
  sparkline, with when it last reported and a link to its page.
-->
<script lang="ts">
	import type { MapStation } from '../types.gen';
	import type { UnitSystem } from '../units';
	import { elevation as fmtElevation, snow as fmtSnow } from '../units';
	import { ago, networkName, sparkline } from './features';
	import { safeHref } from '../links';

	interface Props {
		station: MapStation;
		units: UnitSystem;
	}

	let { station, units }: Props = $props();
	const W = 220;
	const H = 44;
	const line = $derived(sparkline(station.daily, W, H));
	const change = $derived.by(() => {
		const c = station.change24_cm;
		if (c == null) return '–';
		if (Math.abs(c) < 0.5) return 'no change';
		return c > 0 ? `+${fmtSnow(c, units)}` : `−${fmtSnow(-c, units)} (settling or melt)`;
	});
	const day = (iso: string) =>
		new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-US', {
			weekday: 'short',
			timeZone: 'UTC'
		});
</script>

<div class="content">
	<span class="faint where">
		{networkName(station)}{station.elev_m != null
			? ` · ${fmtElevation(station.elev_m, units)}`
			: ''}
	</span>
	<dl>
		<div>
			<dt>Snow depth</dt>
			<dd class="num">{fmtSnow(station.depth_cm, units)}</dd>
		</div>
		<div>
			<dt>Last 24 hours</dt>
			<dd class="num">{change}</dd>
		</div>
	</dl>
	{#if line.d}
		<figure>
			<figcaption class="faint">Depth each morning, the last week</figcaption>
			<svg width={W} height={H + 16} role="img" aria-label="Snow depth over the last week">
				<line class="base" x1="0" x2={W} y1={H} y2={H} />
				<path class="spark" d={line.d} />
				<text class="tick" x="0" y={H + 13}>{day(station.daily[0].date)}</text>
				<text class="tick" x={W} y={H + 13} text-anchor="end"
					>{day(station.daily[station.daily.length - 1].date)}</text
				>
			</svg>
		</figure>
	{/if}
	<p class="faint small">
		Reported {ago(station.obs_time)}. Measured at the station: a single spot, often in a clearing,
		so nearby slopes can differ a lot.
		{#if safeHref(station.url)}
			<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
			<a href={safeHref(station.url)} target="_blank" rel="noopener noreferrer">Station page</a>
		{/if}
	</p>
</div>

<style>
	.content {
		display: grid;
		gap: 10px;
	}
	.where {
		font-size: 0.78rem;
	}
	dl {
		margin: 0;
		display: flex;
		gap: 18px;
	}
	dt {
		font-size: 0.72rem;
		color: var(--text-2);
	}
	dd {
		margin: 0;
		font-weight: 600;
		font-size: 1rem;
	}
	figure {
		margin: 0;
	}
	figcaption {
		font-size: 0.72rem;
		margin-bottom: 2px;
	}
	svg {
		display: block;
		max-width: 100%;
		overflow: visible;
	}
	.base {
		stroke: var(--grid);
	}
	.spark {
		fill: none;
		stroke: #2f63c4;
		stroke-width: 2;
		stroke-linejoin: round;
	}
	.tick {
		fill: var(--text-3);
		font-size: 10.5px;
	}
	.small {
		margin: 0;
		font-size: 0.72rem;
	}
</style>
