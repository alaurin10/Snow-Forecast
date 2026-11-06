<!-- A small line-drawn weather icon. -->
<script lang="ts">
	import type { WxIcon } from '../periodwx';

	let { icon, size = 22, label }: { icon: WxIcon; size?: number; label: string } = $props();

	const CLOUD = 'M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6 11a3.5 3.5 0 0 0 1 7z';
	const CLOUD_HI = 'M7 14h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6 7a3.5 3.5 0 0 0 1 7z';
	const SMALL_CLOUD = 'M9 20h9a3.5 3.5 0 0 0 .4-6.98A5 5 0 0 0 8.6 13.2 3.4 3.4 0 0 0 9 20z';
	const PATHS: Record<WxIcon, string[]> = {
		'clear-day': [
			'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
			'M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4'
		],
		'clear-night': ['M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z'],
		'partly-day': [
			'M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z',
			'M8 2v1.2M2 8h1.2M3.8 3.8l.9.9M12.2 3.8l-.9.9',
			SMALL_CLOUD
		],
		'partly-night': ['M10 3a4.5 4.5 0 1 0 4.5 6.2A3.6 3.6 0 0 1 10 3z', SMALL_CLOUD],
		cloud: [CLOUD],
		fog: ['M4 9h16M4 13h16M6 17h12'],
		rain: [CLOUD_HI, 'M8 17l-1 3M12 17l-1 3M16 17l-1 3'],
		snow: [CLOUD_HI, 'M8 18h.01M12 18h.01M16 18h.01M10 21h.01M14 21h.01'],
		mix: [CLOUD_HI, 'M8 17l-1 3M16 17l-1 3M12 18h.01M12 21h.01'],
		thunder: [CLOUD_HI, 'M12.5 15l-2 3.5h3l-2 3.5']
	};
	const dotted = $derived(icon === 'snow' || icon === 'mix');
</script>

<svg
	class="wx {icon}"
	class:dotted
	viewBox="0 0 24 24"
	width={size}
	height={size}
	role="img"
	aria-label={label}
>
	{#each PATHS[icon] as d, i (i)}<path {d} />{/each}
</svg>

<style>
	.wx {
		flex-shrink: 0;
		fill: none;
		stroke: var(--text-2);
		stroke-width: 1.7;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.wx.dotted path:last-child {
		stroke-width: 2.6;
	}
	.wx.snow path:last-child {
		stroke: var(--snow);
	}
	.wx.rain path:last-child {
		stroke: var(--rain);
	}
	.wx.mix path:last-child {
		stroke: var(--mix);
	}
</style>
