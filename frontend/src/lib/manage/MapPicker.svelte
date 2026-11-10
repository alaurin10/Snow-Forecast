<!--
  A topo map for placing a tour's pins. Tap the map to put the selected pin
  there; drag a pin to adjust it. Tiles: OpenTopoMap (CC-BY-SA), loaded by the
  browser only on this owner-only page.
-->
<script lang="ts">
	import 'leaflet/dist/leaflet.css';
	import type { Map as LeafletMap, Marker } from 'leaflet';

	export type PinBand = 'base' | 'mid' | 'summit';
	export type Pins = Partial<Record<PinBand, { lat: number; lon: number }>>;

	interface Props {
		pins: Pins;
		active: PinBand;
		onpick: (band: PinBand, lat: number, lon: number) => void;
		center?: [number, number];
	}

	let { pins, active, onpick, center = [47.6, -121.3] }: Props = $props();
	let el = $state<HTMLDivElement>();
	let map: LeafletMap | null = null;
	let L: typeof import('leaflet') | null = null;
	const markers: Partial<Record<PinBand, Marker>> = {};
	const LABEL: Record<PinBand, string> = { base: 'Trailhead', mid: 'Mid', summit: 'High point' };
	const COLOR: Record<PinBand, string> = { base: '#1baf7a', mid: '#eb6834', summit: '#2a78d6' };

	$effect(() => {
		if (!el) return;
		let cancelled = false;
		import('leaflet').then((mod) => {
			if (cancelled || !el) return;
			L = mod.default ?? mod;
			map = L.map(el, { zoomControl: true }).setView(center, 9);
			// Through the server's tile cache, like the main map: no third-party requests.
			L.tileLayer('/api/tiles/otm/{z}/{x}/{y}.png', {
				maxZoom: 17,
				attribution:
					'Map © <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>, SRTM | Style © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'
			}).addTo(map);
			map.on('click', (e) => onpick(activeBand(), e.latlng.lat, e.latlng.lng));
			sync();
		});
		return () => {
			cancelled = true;
			map?.remove();
			map = null;
		};
	});

	// The click handler reads the current band through this, not a stale capture.
	let currentActive: PinBand = 'summit';
	const activeBand = () => currentActive;
	$effect(() => {
		currentActive = active;
	});

	function sync() {
		if (!map || !L) return;
		for (const band of ['base', 'mid', 'summit'] as PinBand[]) {
			const p = pins[band];
			const existing = markers[band];
			if (!p) {
				existing?.remove();
				delete markers[band];
				continue;
			}
			if (existing) {
				existing.setLatLng([p.lat, p.lon]);
				continue;
			}
			const icon = L.divIcon({
				className: 'pin',
				html: `<span style="background:${COLOR[band]}"></span><b>${LABEL[band]}</b>`,
				iconSize: [14, 14],
				iconAnchor: [7, 7]
			});
			const m = L.marker([p.lat, p.lon], { icon, draggable: true }).addTo(map);
			m.on('dragend', () => {
				const ll = m.getLatLng();
				onpick(band, ll.lat, ll.lng);
			});
			markers[band] = m;
		}
	}

	$effect(() => {
		// Re-sync markers whenever the pins change.
		void JSON.stringify(pins);
		sync();
	});
</script>

<div
	class="map"
	bind:this={el}
	role="application"
	aria-label="Map: tap to place the selected pin"
></div>

<style>
	.map {
		height: 340px;
		border-radius: 10px;
		border: 1px solid var(--border);
		overflow: hidden;
		touch-action: pan-x pan-y;
	}
	:global(.pin span) {
		display: block;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		border: 2px solid #fff;
		box-shadow: 0 0 0 1px rgb(0 0 0 / 0.4);
	}
	:global(.pin b) {
		position: absolute;
		left: 16px;
		top: -2px;
		white-space: nowrap;
		font:
			600 11px/1.2 system-ui,
			sans-serif;
		color: #111;
		background: rgb(255 255 255 / 0.85);
		padding: 1px 4px;
		border-radius: 4px;
	}
</style>
