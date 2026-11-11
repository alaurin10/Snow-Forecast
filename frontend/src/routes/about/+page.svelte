<script lang="ts">
	import { resolve } from '$app/paths';
	import { getMeta } from '../../lib/api';
	import type { MetaOut } from '../../lib/types.gen';

	let meta = $state<MetaOut | null>(null);
	$effect(() => {
		getMeta()
			.then((m) => (meta = m))
			.catch(() => {}); // the version line just stays out
	});

	// Every source the app shows, and the terms it is used under.
	const SOURCES: { name: string; href: string; what: string; terms: string }[] = [
		{
			name: 'Open-Meteo',
			href: 'https://open-meteo.com/',
			what: 'Weather models (GFS, ECMWF, GEM, ICON, HRRR, NBM, HRDPS) and ensembles',
			terms: 'CC BY 4.0'
		},
		{
			name: 'National Weather Service (NOAA)',
			href: 'https://www.weather.gov/',
			what: 'Watches and warnings, forecast offices; HRRR and National Blend of Models forecasts on the map (NOAA Open Data Dissemination)',
			terms: 'US public domain'
		},
		{
			name: 'Environment and Climate Change Canada',
			href: 'https://eccc-msc.github.io/open-data/',
			what: 'Radar, the radar nowcast, HRDPS, RDPS and GDPS forecasts and snow totals on the map',
			terms: 'Open Government Licence – Canada'
		},
		{
			name: 'RainViewer',
			href: 'https://www.rainviewer.com/',
			what: 'Backup radar on the map',
			terms: 'Free API, with credit'
		},
		{
			name: 'NRCS SNOTEL (USDA)',
			href: 'https://www.nrcs.usda.gov/wps/portal/wcc/home/',
			what: 'Snow depth and snow water at US stations',
			terms: 'US public domain'
		},
		{
			name: 'BC River Forecast Centre',
			href: 'https://www2.gov.bc.ca/gov/content/environment/air-land-water/water/drought-flooding-dikes-dams/river-forecast-centre',
			what: 'Automated snow pillows in British Columbia',
			terms: 'Open Government Licence – British Columbia'
		},
		{
			name: 'avalanche.org',
			href: 'https://avalanche.org/',
			what: 'US avalanche danger ratings, shown as each center publishes them',
			terms: 'Each center’s own terms'
		},
		{
			name: 'Avalanche Canada',
			href: 'https://avalanche.ca/',
			what: 'Canadian avalanche danger ratings, shown as published',
			terms: 'Avalanche Canada’s terms'
		},
		{
			name: 'OpenStreetMap and OpenSkiMap',
			href: 'https://www.openstreetmap.org/copyright',
			what: 'Ski runs, lifts, peaks and the ski-area list',
			terms: '© OpenStreetMap contributors, ODbL'
		},
		{
			name: 'OpenTopoMap',
			href: 'https://opentopomap.org/',
			what: 'Topographic base map',
			terms: 'CC-BY-SA'
		},
		{
			name: 'Esri',
			href: 'https://www.esri.com/',
			what: 'Topographic and satellite base maps',
			terms: 'Esri terms of use'
		},
		{
			name: 'Mapterhorn',
			href: 'https://mapterhorn.com/attribution/',
			what: 'Elevation for 3D terrain, shading, slope, aspect and contours (USGS 3DEP, NRCan HRDEM, Copernicus GLO-30 and others)',
			terms: 'Open data, each source under its own licence (see Mapterhorn)'
		},
		{
			name: 'Mapzen terrain tiles on AWS',
			href: 'https://registry.opendata.aws/terrain-tiles/',
			what: 'Backup elevation when Mapterhorn is unavailable',
			terms: 'Various open licences (see the registry)'
		}
	];
</script>

<svelte:head>
	<title>About · Snow Watch</title>
	<meta
		name="description"
		content="What Snow Watch is, where its data comes from, and its limits."
	/>
</svelte:head>

<div class="pagehead">
	<a class="back" href={resolve('/settings')}>← Settings</a>
	<h1>About Snow Watch</h1>
</div>

<div class="grid">
	<section class="card">
		<h2>What it is</h2>
		<p>
			Snow Watch puts several weather models side by side for ski resorts and backcountry zones: a
			consensus of the models, the range the ensembles allow, how much the models disagree, and what
			the snow stations measured. It updates four times a day.
		</p>
		<h2>Please read</h2>
		<p>
			<strong>Forecasts are estimates.</strong> Model snowfall is derived from forecast precipitation
			and temperature, not measured, and can be badly wrong, especially in the mountains and more than
			a few days ahead.
		</p>
		<p>
			<strong>Snow Watch never tells you whether terrain is safe.</strong> Avalanche ratings are shown
			exactly as the avalanche centers publish them and disappear when they expire. Always read the full
			forecast from your local center, and travel in avalanche terrain only with the training, equipment
			and judgement it needs.
		</p>
		<p class="muted small">Snow Watch is provided as is, without any warranty.</p>
	</section>

	<section class="card">
		<h2>Privacy</h2>
		<ul class="small">
			<li>No accounts, no ads, no analytics or tracking.</li>
			<li>Your settings (units, theme, saved offline maps) stay in this browser.</li>
			<li>
				“Show my location” on the map uses your device’s position on this device only; it is never
				sent to the server.
			</li>
			<li>
				Turning on alerts stores your browser’s push address and your alert choices on the server,
				and nothing else. Turning alerts off deletes them.
			</li>
			<li>Webcam pictures load straight from each resort’s own website.</li>
			<li>The server keeps ordinary request logs for troubleshooting.</li>
		</ul>
		{#if meta}
			<p class="faint small">
				Version {meta.version}{meta.commit ? ` (${meta.commit.slice(0, 7)})` : ''}
			</p>
		{/if}
	</section>

	<section class="card wide">
		<h2>Data sources</h2>
		<p class="muted small">Snow Watch is not affiliated with or endorsed by any of these.</p>
		<ul class="sources">
			{#each SOURCES as s (s.name)}
				<li>
					<!-- External sites: resolve() is only for routes in this app. -->
					<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
					<a href={s.href} rel="noopener noreferrer" target="_blank">{s.name}</a>
					<span class="muted">{s.what}.</span>
					<span class="faint">{s.terms}</span>
				</li>
			{/each}
		</ul>
	</section>
</div>

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
	@media (min-width: 900px) {
		.grid {
			grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
			align-items: start;
		}
		.wide {
			grid-column: 1 / -1;
		}
	}
	h2 {
		font-size: 1rem;
		margin: 0 0 6px;
	}
	h2 + p,
	p + h2 {
		margin-top: 12px;
	}
	p {
		line-height: 1.5;
	}
	.small {
		font-size: 0.85rem;
	}
	ul.small {
		padding-left: 18px;
		line-height: 1.5;
	}
	.sources {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		gap: 8px;
		font-size: 0.88rem;
	}
	.sources li {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 8px;
	}
</style>
