<!--
  Every location on a topo map. Each marker shows the next-5-day snow on the
  Calendar's colour ramp, with a ring in the avalanche danger colour when the
  center's rating is current. Tap a marker for the numbers and a link.
  With `radar`, the last two hours of weather radar loop over the terrain.
-->
<script lang="ts">
	import 'leaflet/dist/leaflet.css';
	import type { Map as LeafletMap } from 'leaflet';
	import type { OverviewRow } from '../types.gen';
	import { bucket } from '../calendar';
	import { dangerWord } from '../conditions';
	import { snowNum, type UnitSystem } from '../units';
	import { frameLabel, loadRadar, RADAR_MAX_NATIVE_ZOOM, type RadarFrame } from '../radar';

	interface Props {
		rows: OverviewRow[];
		units: UnitSystem;
		href: (id: string) => string;
		/** Show the weather radar layer and its controls. */
		radar?: boolean;
	}

	let { rows, units, href, radar = false }: Props = $props();
	let el = $state<HTMLDivElement>();
	let map: LeafletMap | null = null;
	let L: typeof import('leaflet') | null = null;
	let layer: import('leaflet').LayerGroup | null = null;

	// Radar: one tile layer per frame, all loaded, only the current one visible.
	let frames = $state<RadarFrame[]>([]);
	let frame = $state(0);
	let radarOn = $state(true);
	let playing = $state(true);
	let radarError = $state(false);
	let radarLayers: import('leaflet').TileLayer[] = [];
	const RADAR_OPACITY = 0.7;

	function buildRadar() {
		if (!map || !L) return;
		for (const l of radarLayers) l.remove();
		radarLayers = frames.map((f) =>
			L!
				.tileLayer(f.url, {
					pane: 'radar',
					opacity: 0,
					maxNativeZoom: RADAR_MAX_NATIVE_ZOOM,
					maxZoom: 15,
					attribution: 'Radar © <a href="https://www.rainviewer.com">RainViewer</a>'
				})
				.addTo(map!)
		);
		frame = Math.max(0, frames.length - 1);
		showFrame();
	}
	function showFrame() {
		radarLayers.forEach((l, i) => l.setOpacity(radarOn && i === frame ? RADAR_OPACITY : 0));
	}
	async function refreshRadar() {
		try {
			frames = await loadRadar();
			radarError = false;
			buildRadar();
		} catch {
			radarError = true;
		}
	}

	$effect(() => {
		void frame;
		void radarOn;
		showFrame();
	});
	// Loop through the frames, holding a moment on the latest one.
	$effect(() => {
		if (!radar || !playing || !radarOn || frames.length < 2) return;
		const id = setInterval(() => {
			frame = (frame + 1) % frames.length;
		}, 650);
		return () => clearInterval(id);
	});
	$effect(() => {
		if (!radar) return;
		const id = setInterval(refreshRadar, 10 * 60 * 1000);
		return () => clearInterval(id);
	});

	const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

	$effect(() => {
		if (!el) return;
		let cancelled = false;
		import('leaflet').then((mod) => {
			if (cancelled || !el) return;
			L = mod.default ?? mod;
			map = L.map(el, { zoomControl: true, scrollWheelZoom: false });
			L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
				maxZoom: 15,
				attribution:
					'Map © <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>, SRTM | Style © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'
			}).addTo(map);
			layer = L.layerGroup().addTo(map);
			if (radar) {
				// Between the terrain and the markers.
				map.createPane('radar').style.zIndex = '350';
				refreshRadar();
			}
			draw();
		});
		return () => {
			cancelled = true;
			map?.remove();
			map = null;
			radarLayers = [];
		};
	});

	$effect(() => {
		void rows;
		void units;
		draw();
	});

	function draw() {
		if (!map || !L || !layer) return;
		layer.clearLayers();
		const placed = rows.filter((r) => r.lat !== null && r.lat !== undefined && r.lon != null);
		for (const r of placed) {
			const b = bucket(r.next5_cm);
			const danger = r.danger?.status === 'current' && r.danger.level ? r.danger.level : 0;
			const label = snowNum(r.next5_cm, units);
			const icon = L.divIcon({
				className: 'snowpin',
				html: `<span class="dot b${b}${danger ? ` ring d${danger}` : ''}">${esc(label)}</span>`,
				iconSize: [34, 34],
				iconAnchor: [17, 17]
			});
			const unit = units === 'imperial' ? 'in' : 'cm';
			const dangerLine = danger ? `<div>Avalanche ${danger} · ${dangerWord(danger)}</div>` : '';
			L.marker([r.lat!, r.lon!], { icon, title: r.name, alt: r.name })
				.bindPopup(
					`<strong>${esc(r.name)}</strong><div>${esc(label)} ${unit} in the next 5 days</div>` +
						`${dangerLine}<a href="${esc(href(r.id))}">Open forecast →</a>`
				)
				.addTo(layer);
		}
		if (placed.length) {
			const bounds = L.latLngBounds(placed.map((r) => [r.lat!, r.lon!] as [number, number]));
			map.fitBounds(bounds.pad(0.25), { maxZoom: 9 });
		}
	}
</script>

<div class="wrap">
	<div
		class="map"
		class:tall={radar}
		bind:this={el}
		role="region"
		aria-label="Map of locations"
	></div>
	{#if radar}
		<div class="radar glass">
			<button
				class="toggle"
				aria-pressed={radarOn}
				onclick={() => (radarOn = !radarOn)}
				title="Show or hide the radar">Radar</button
			>
			{#if radarOn && frames.length}
				<button
					class="play"
					onclick={() => (playing = !playing)}
					aria-label={playing ? 'Pause radar loop' : 'Play radar loop'}
				>
					<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
						{#if playing}<path d="M8 5v14M16 5v14" />{:else}<path d="M7 5l12 7-12 7z" />{/if}
					</svg>
				</button>
				<input
					type="range"
					min="0"
					max={frames.length - 1}
					bind:value={frame}
					oninput={() => (playing = false)}
					aria-label="Radar time"
					aria-valuetext={frameLabel(frames[frame].time)}
				/>
				<span class="time num">{frameLabel(frames[frame].time)}</span>
			{:else if radarError}
				<span class="time">Radar unavailable right now</span>
			{/if}
		</div>
	{/if}
</div>
<p class="faint small legend">
	<span
		>Numbers are the next 5 days of snow ({units === 'imperial' ? 'in' : 'cm'}). A coloured ring is
		the avalanche danger, when rated.</span
	>
	{#if radar}<span>
			Radar shows the last 2 hours; brighter is heavier, and snow is drawn in its own colours.</span
		>{/if}
</p>

<style>
	.wrap {
		position: relative;
	}
	.map {
		height: min(70vh, 560px);
		border-radius: var(--radius);
		overflow: hidden;
		border: 1px solid var(--border);
	}
	.map.tall {
		height: min(78vh, 760px);
	}
	.radar {
		position: absolute;
		left: 12px;
		right: 12px;
		bottom: 28px;
		z-index: 1001;
		max-width: 520px;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 6px 12px 6px 6px;
		border-radius: 999px;
		font-size: 0.8rem;
	}
	.toggle,
	.play {
		border: 0;
		border-radius: 999px;
		cursor: pointer;
		flex-shrink: 0;
	}
	.toggle {
		padding: 7px 14px;
		font-weight: 600;
		background: var(--surface-2);
		color: var(--text-2);
	}
	.toggle[aria-pressed='true'] {
		background: var(--accent);
		color: var(--surface);
	}
	.play {
		width: 32px;
		height: 32px;
		display: grid;
		place-items: center;
		background: var(--surface);
		color: var(--text);
	}
	.play svg {
		fill: currentColor;
		stroke: currentColor;
		stroke-width: 2.4;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.radar input {
		flex: 1;
		min-width: 60px;
		accent-color: var(--accent);
	}
	.time {
		white-space: nowrap;
		color: var(--text);
		font-weight: 600;
	}
	.legend {
		margin: 6px 0 0;
		font-size: 0.8rem;
	}
	:global(.snowpin .dot) {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 50%;
		font: 600 12px/1 var(--font-num, sans-serif);
		box-shadow: 0 1px 3px rgb(0 0 0 / 0.35);
		border: 2px solid #fff;
	}
	:global(.snowpin .dot.ring) {
		border-width: 4px;
	}
	:global(.snowpin .b0) {
		background: var(--c0);
		color: var(--text);
	}
	:global(.snowpin .b1) {
		background: var(--c1);
		color: var(--c-ink-light);
	}
	:global(.snowpin .b2) {
		background: var(--c2);
		color: var(--c-ink-light);
	}
	:global(.snowpin .b3) {
		background: var(--c3);
		color: var(--c-ink-dark);
	}
	:global(.snowpin .b4) {
		background: var(--c4);
		color: var(--c-ink-dark);
	}
	:global(.snowpin .b5) {
		background: var(--c5);
		color: var(--c-ink-dark);
	}
	:global(.snowpin .d1) {
		border-color: var(--d1);
	}
	:global(.snowpin .d2) {
		border-color: var(--d2);
	}
	:global(.snowpin .d3) {
		border-color: var(--d3);
	}
	:global(.snowpin .d4) {
		border-color: var(--d4);
	}
	:global(.snowpin .d5) {
		border-color: var(--d5);
	}
</style>
