<!--
  Every location on a topo map. Each marker shows the next-5-day snow on the
  Calendar's colour ramp, with a ring in the avalanche danger colour when the
  center's rating is current. Tap a marker for the numbers and a link.
-->
<script lang="ts">
	import 'leaflet/dist/leaflet.css';
	import type { Map as LeafletMap } from 'leaflet';
	import type { OverviewRow } from '../types.gen';
	import { bucket } from '../calendar';
	import { dangerWord } from '../conditions';
	import { snowNum, type UnitSystem } from '../units';

	interface Props {
		rows: OverviewRow[];
		units: UnitSystem;
		href: (id: string) => string;
	}

	let { rows, units, href }: Props = $props();
	let el = $state<HTMLDivElement>();
	let map: LeafletMap | null = null;
	let L: typeof import('leaflet') | null = null;
	let layer: import('leaflet').LayerGroup | null = null;

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
			draw();
		});
		return () => {
			cancelled = true;
			map?.remove();
			map = null;
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

<div class="map" bind:this={el} role="region" aria-label="Map of locations"></div>
<p class="faint small legend">
	Numbers are the next 5 days of snow ({units === 'imperial' ? 'in' : 'cm'}). A coloured ring is the
	avalanche danger, when rated.
</p>

<style>
	.map {
		height: min(70vh, 560px);
		border-radius: 12px;
		overflow: hidden;
		border: 1px solid var(--border);
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
