<!--
  Push alerts for this device. Turning them on asks the browser for permission
  (it must follow a tap), subscribes through the app's service worker and saves
  which locations and alerts to send. On iPhone this only works from the app
  added to the Home Screen.
-->
<script lang="ts">
	import { getLocations } from '../api';
	import { prefs } from '../prefs.svelte';
	import {
		currentSubscription,
		pushSupport,
		saveChoices,
		sendTest,
		serverKey,
		turnOff,
		turnOn,
		type PushSupport
	} from '../push';
	import type { LocationSummary } from '../types.gen';

	const TYPES: [string, string][] = [
		['powder_day', 'Powder days (6 in or more)'],
		['storm_incoming', 'Storms on the way (12 in in 48 h)'],
		['wind_hold', 'Wind holds at resorts'],
		['avalanche_danger', 'Avalanche danger High or Extreme']
	];

	let support = $state<PushSupport>('unsupported');
	let key = $state<string | null | undefined>(undefined); // undefined = still checking
	let on = $state(false);
	let busy = $state(false);
	let message = $state<string | null>(null);
	let locations = $state<LocationSummary[]>([]);
	let picked = $state<string[]>([]); // empty = all
	let types = $state<string[]>(['powder_day', 'storm_incoming']);

	$effect(() => {
		support = pushSupport();
		serverKey()
			.then((k) => (key = k))
			.catch(() => (key = null));
		getLocations()
			.then((l) => (locations = l))
			.catch(() => {});
		if (support === 'ok') {
			currentSubscription()
				.then((s) => (on = s !== null))
				.catch(() => {});
		}
	});

	const choices = () => ({ locations: picked, types, units: prefs.units });

	async function run(action: () => Promise<{ ok: boolean; detail?: string | null }>, done: string) {
		busy = true;
		message = null;
		try {
			const res = await action();
			message = res.ok ? done : (res.detail ?? 'That didn’t work.');
			return res.ok;
		} catch (e) {
			message = `This device couldn't sign up with its push service (${(e as Error).message}). Try again, or check the RUNBOOK troubleshooting table.`;
			return false;
		} finally {
			busy = false;
		}
	}

	const enable = async () => {
		if (!key) return;
		if (await run(() => turnOn(key!, choices()), 'Alerts are on for this device.')) on = true;
		support = pushSupport();
	};
	const disable = async () => {
		if (await run(turnOff, 'Alerts are off for this device.')) on = false;
	};
	const toggle = (list: string[], v: string) =>
		list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
</script>

<section class="card">
	<h2>Alerts</h2>
	{#if support === 'ios-home-screen'}
		<p class="small">
			On iPhone and iPad, alerts work from the Home Screen app: tap Share, then <strong
				>Add to Home Screen</strong
			>, open Snow Watch from there and come back here.
		</p>
	{:else if support === 'unsupported'}
		<p class="small muted">This browser can't receive push alerts.</p>
	{:else if support === 'denied'}
		<p class="small muted">
			Notifications are blocked for this site. Allow them in the browser's site settings, then
			reload.
		</p>
	{:else if key === undefined}
		<p class="small muted">Checking…</p>
	{:else if key === null}
		<p class="small muted">Push alerts aren't set up on the server yet.</p>
	{:else}
		<p class="small muted">
			Get a notification when a powder day or storm first shows up in the forecast.
		</p>
		<fieldset>
			<legend>Send me</legend>
			{#each TYPES as [t, label] (t)}
				<label class="check"
					><input
						type="checkbox"
						checked={types.includes(t)}
						onchange={() => (types = toggle(types, t))}
					/>
					{label}</label
				>
			{/each}
		</fieldset>
		<fieldset>
			<legend>For</legend>
			<label class="check"
				><input type="checkbox" checked={picked.length === 0} onchange={() => (picked = [])} /> Every
				location</label
			>
			{#each locations as l (l.id)}
				<label class="check"
					><input
						type="checkbox"
						checked={picked.includes(l.id)}
						onchange={() => (picked = toggle(picked, l.id))}
					/>
					{l.name}</label
				>
			{/each}
		</fieldset>
		<div class="actions">
			{#if !on}
				<button class="btn primary" disabled={busy || !types.length} onclick={enable}
					>Turn on alerts</button
				>
			{:else}
				<button
					class="btn primary"
					disabled={busy || !types.length}
					onclick={() => run(() => saveChoices(choices()), 'Saved.')}>Save</button
				>
				<button class="btn" disabled={busy} onclick={() => run(sendTest, 'Test sent.')}
					>Send a test</button
				>
				<button class="btn" disabled={busy} onclick={disable}>Turn off</button>
			{/if}
		</div>
	{/if}
	{#if message}<p class="small msg" role="status">{message}</p>{/if}
</section>

<style>
	h2 {
		margin: 0 0 6px;
	}
	.small {
		font-size: 0.85rem;
	}
	fieldset {
		border: 0;
		padding: 0;
		margin: 8px 0;
		display: grid;
		gap: 4px;
	}
	legend {
		font-size: 0.8rem;
		color: var(--text-2);
		margin-bottom: 2px;
	}
	.check {
		display: flex;
		gap: 8px;
		align-items: center;
		font-size: 0.9rem;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.msg {
		margin: 8px 0 0;
	}
</style>
