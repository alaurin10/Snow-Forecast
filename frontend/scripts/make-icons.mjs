// Render the app icons from one SVG with the preinstalled Playwright Chromium.
//   node scripts/make-icons.mjs
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

// A six-armed snowflake on the snow-blue square. `pad` shrinks the art for
// maskable icons, whose outer 20% may be cropped by the phone.
const svg = (pad) => {
	const arm = (a) =>
		`<g transform="rotate(${a} 50 50)"><line x1="50" y1="50" x2="50" y2="20"/><line x1="50" y1="30" x2="42" y2="23"/><line x1="50" y1="30" x2="58" y2="23"/></g>`;
	return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<rect width="100" height="100" fill="#2a78d6"/>
<g transform="translate(50 50) scale(${1 - pad}) translate(-50 -50)" stroke="#fff" stroke-width="5" stroke-linecap="round">
${[0, 60, 120, 180, 240, 300].map(arm).join('')}
</g></svg>`;
};

const icons = [
	{ file: 'icon-192.png', size: 192, pad: 0.12 },
	{ file: 'icon-512.png', size: 512, pad: 0.12 },
	{ file: 'maskable-512.png', size: 512, pad: 0.32 },
	{ file: 'apple-touch-icon.png', size: 180, pad: 0.16 }
];

const browser = await chromium.launch();
for (const { file, size, pad } of icons) {
	const page = await browser.newPage({ viewport: { width: size, height: size } });
	await page.setContent(
		`<body style="margin:0">${svg(pad).replace('<svg ', `<svg width="${size}" height="${size}" `)}</body>`
	);
	await page.screenshot({ path: `static/icons/${file}`, omitBackground: false });
	await page.close();
}
await browser.close();
const { writeFileSync } = await import('node:fs');
writeFileSync('static/icons/icon.svg', svg(0.12));
console.log('icons written to static/icons/');
