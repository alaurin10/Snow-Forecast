// "Where am I" on the Map: a blue dot, a faint circle for how sure the fix is, and a
// cone for the way you're facing (compass) or heading (GPS, when moving).
//
// Everything stays on the device: positions are never sent anywhere.

import type { GeoJSONSource, Map as MlMap, Marker } from 'maplibre-gl';

export type LocState = 'off' | 'locating' | 'following' | 'shown' | 'denied' | 'unavailable';

type Ml = typeof import('maplibre-gl');

const SRC = 'userloc-accuracy';
const FOLLOW_ZOOM = 14;

/** A circle `r` metres around a point, as a polygon (good enough at these sizes). */
export function circle(lon: number, lat: number, r: number, steps = 64): GeoJSON.Polygon {
	const dLat = r / 111_320;
	const dLon = r / (111_320 * Math.cos((lat * Math.PI) / 180));
	const ring: [number, number][] = [];
	for (let i = 0; i <= steps; i++) {
		const a = (i / steps) * 2 * Math.PI;
		ring.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
	}
	return { type: 'Polygon', coordinates: [ring] };
}

/** Compass heading in degrees clockwise from north, from a device orientation event. */
export function compassHeading(e: DeviceOrientationEvent): number | null {
	const ios = (e as DeviceOrientationEvent & { webkitCompassHeading?: number })
		.webkitCompassHeading;
	if (typeof ios === 'number' && !Number.isNaN(ios)) return ios;
	if (e.absolute && e.alpha !== null) return (360 - e.alpha) % 360;
	return null;
}

export class UserLocation {
	state: LocState = 'off';
	/** Called whenever `state` changes, so the button can redraw. */
	onChange: (s: LocState) => void = () => {};

	private watch: number | null = null;
	private marker: Marker | null = null;
	private el: HTMLDivElement | null = null;
	private last: GeolocationPosition | null = null;
	private compass: number | null = null;
	private firstFix = true;
	private orientEvent: 'deviceorientationabsolute' | 'deviceorientation' | null = null;

	constructor(
		private map: MlMap,
		private ml: Ml
	) {}

	static supported(): boolean {
		return typeof navigator !== 'undefined' && 'geolocation' in navigator && isSecureContext;
	}

	/** The button: start, re-centre after panning away, or stop. Call from a tap. */
	toggle(): void {
		if (this.state === 'shown' && this.last) {
			this.set('following');
			this.centre(this.last, true);
		} else if (this.watch !== null) this.stop();
		else this.start();
	}

	start(): void {
		if (!UserLocation.supported()) return this.set('unavailable');
		// iPhone asks for the compass separately, and only straight from a tap.
		const DOE = (
			globalThis as {
				DeviceOrientationEvent?: { requestPermission?: () => Promise<string> };
			}
		).DeviceOrientationEvent;
		if (typeof DOE?.requestPermission === 'function') {
			DOE.requestPermission()
				.then((r) => r === 'granted' && this.listenCompass())
				.catch(() => {});
		} else this.listenCompass();

		this.firstFix = true;
		this.set('locating');
		this.map.on('dragstart', this.onUserMove);
		this.map.on('rotate', this.onRotate);
		this.watch = navigator.geolocation.watchPosition(this.onPos, this.onErr, {
			enableHighAccuracy: true,
			maximumAge: 5000,
			timeout: 30000
		});
	}

	stop(): void {
		if (this.watch !== null) navigator.geolocation.clearWatch(this.watch);
		this.watch = null;
		if (this.orientEvent) removeEventListener(this.orientEvent, this.onOrient as EventListener);
		this.orientEvent = null;
		this.compass = null;
		this.map.off('dragstart', this.onUserMove);
		this.map.off('rotate', this.onRotate);
		this.marker?.remove();
		this.marker = null;
		this.el = null;
		this.last = null;
		(this.map.getSource(SRC) as GeoJSONSource | undefined)?.setData(empty());
		if (this.state !== 'denied' && this.state !== 'unavailable') this.set('off');
	}

	private set(s: LocState) {
		if (this.state === s) return;
		this.state = s;
		this.onChange(s);
	}

	private listenCompass() {
		// Android gives true north on the "absolute" event; iPhone on the plain one.
		this.orientEvent =
			'ondeviceorientationabsolute' in globalThis
				? 'deviceorientationabsolute'
				: 'deviceorientation';
		addEventListener(this.orientEvent, this.onOrient as EventListener);
	}

	private onOrient = (e: DeviceOrientationEvent) => {
		const h = compassHeading(e);
		if (h === null) return;
		this.compass = h;
		this.drawHeading();
	};

	private onPos = (p: GeolocationPosition) => {
		this.last = p;
		const { longitude: lon, latitude: lat, accuracy } = p.coords;
		this.ensureLayers();
		(this.map.getSource(SRC) as GeoJSONSource | undefined)?.setData({
			type: 'Feature',
			properties: {},
			geometry: circle(lon, lat, Math.max(accuracy, 5))
		});
		if (!this.marker) {
			this.el = document.createElement('div');
			this.el.className = 'userloc';
			this.el.setAttribute('role', 'img');
			this.el.setAttribute('aria-label', 'You are here');
			this.el.innerHTML = '<span class="cone"></span><span class="me"></span>';
			this.marker = new this.ml.Marker({
				element: this.el,
				rotationAlignment: 'map',
				pitchAlignment: 'map',
				opacityWhenCovered: '1'
			})
				.setLngLat([lon, lat])
				.addTo(this.map);
		} else this.marker.setLngLat([lon, lat]);
		this.drawHeading();
		if (this.firstFix) {
			this.firstFix = false;
			this.set('following');
			this.centre(p, true);
		} else if (this.state === 'following') this.centre(p, false);
	};

	private onErr = (e: GeolocationPositionError) => {
		if (e.code === e.PERMISSION_DENIED) {
			this.stop();
			this.set('denied');
		} else if (!this.last) {
			// No fix yet (indoors, or the GPS warming up): keep trying, but say so.
			this.set('unavailable');
		}
	};

	/** Panning by hand stops following; the dot keeps updating. */
	private onUserMove = (e: { originalEvent?: unknown }) => {
		if (e.originalEvent && this.state === 'following') this.set('shown');
	};

	private onRotate = () => this.drawHeading();

	private centre(p: GeolocationPosition, first: boolean) {
		const centre: [number, number] = [p.coords.longitude, p.coords.latitude];
		if (first) {
			this.map.flyTo({
				center: centre,
				zoom: Math.max(this.map.getZoom(), FOLLOW_ZOOM),
				duration: 1800,
				essential: true
			});
		} else if (!this.map.isMoving()) {
			this.map.easeTo({ center: centre, duration: 600 });
		}
	}

	/** Compass when there is one; otherwise the GPS course, which only exists when moving. */
	private drawHeading() {
		if (!this.marker || !this.el) return;
		const c = this.last?.coords;
		const course = c && c.heading !== null && (c.speed ?? 0) > 0.7 ? c.heading : null;
		const h = this.compass ?? course;
		this.el.classList.toggle('has-heading', h !== null && !Number.isNaN(h));
		if (h !== null && !Number.isNaN(h)) this.marker.setRotation(h);
	}

	private ensureLayers() {
		if (this.map.getSource(SRC)) return;
		this.map.addSource(SRC, { type: 'geojson', data: empty() });
		this.map.addLayer({
			id: 'userloc-accuracy',
			type: 'fill',
			source: SRC,
			paint: { 'fill-color': '#1a73e8', 'fill-opacity': 0.12 }
		});
		this.map.addLayer({
			id: 'userloc-accuracy-edge',
			type: 'line',
			source: SRC,
			paint: { 'line-color': '#1a73e8', 'line-opacity': 0.45, 'line-width': 1 }
		});
	}
}

function empty(): GeoJSON.FeatureCollection {
	return { type: 'FeatureCollection', features: [] };
}
