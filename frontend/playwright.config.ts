// Browser smoke tests against the real API serving the built app, with fixture data.
//   npm run build && npm run e2e
import { defineConfig, devices } from '@playwright/test';

const desktop = { viewport: { width: 1280, height: 860 } };

export default defineConfig({
	testDir: 'e2e',
	timeout: 30_000,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? [['github'], ['list']] : 'list',
	use: { baseURL: 'http://localhost:8019', trace: 'off' },
	projects: [
		{ name: 'phone', use: { ...devices['Pixel 7'] }, grepInvert: /@solo/ },
		{ name: 'desktop', use: desktop, grepInvert: /@solo/ },
		// Tests tagged @solo draw the map in 3D, which headless Chromium does in software
		// (SwiftShader) on every core it can get. Next to another test they starve its page
		// (on a slow CI runner a click or an evaluate there waited 30 s) and run slow
		// themselves, so they run last, one at a time, with the machine to themselves.
		{
			name: 'solo',
			use: desktop,
			grep: /@solo/,
			workers: 1,
			dependencies: ['phone', 'desktop']
		}
	],
	webServer: {
		command: 'bash e2e/serve.sh',
		url: 'http://localhost:8019/api/health',
		timeout: 120_000,
		reuseExistingServer: !process.env.CI
	}
});
