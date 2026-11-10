<!--
  Push alerts for this device. Turning them on asks the browser for permission
  (it must follow a tap), subscribes through the app's service worker and saves
  which locations and alerts to send. Once on, every change saves itself. On
  iPhone this only works from the app added to the Home Screen.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { getLocations, getMeta } from '../api';
	import { prefs } from '../prefs.svelte';
	import {
		currentSubscription,
		pushSupport,
		saveChoices,
		savedChoices,
		sendTest,
		serverKey,
		turnOff,
		turnOn,
		type PushSupport
	} from '../push';
	import type { LocationSummary, MetaOut } from '../types.gen';

	// Thresholds come from the server's settings, in the viewer's units.
	let meta = $state<MetaOut | null>(null);
	const amount = (cm: number | undefined) =>
		cm === undefined
			? ''
			: prefs.units === 'imperial'
				? `${Math.round(cm / 2.54)} in`
				: `${Math.round(cm)} cm`;
	const TYPES = $derived<[string, string][]>([
		['powder_day', meta ? `Powder days (${amount(meta.powder_cm)} or more)` : 'Powder days'],
		[
			'storm_incoming',
			meta ? `Storms on the way (${amount(meta.storm_cm)} in 48 h)` : 'Storms on the way'
		],
		['wind_hold', 'Wind holds at resorts'],
		['avalanche_danger', 'Avalanche danger High or Extreme']
	]);

	let support = $state<PushSupport>('unsupported');
	let key = $state<string | null | undefined>(undefined); // undefined = still checking
	let on = $state(false);
	let busy = $state(false);
	let message = $state<string | null>(null);
	let locations = $state<LocationSummary[]>([]);
	let picked = $state<string[]>([]); // empty = all
	let types = $state<string[]>(['powder_day', 'storm_incoming']);
	let listError = $state(false);

	$effect(() => {
		support = pushSupport();
		serverKey()
			.then((k) => (key = k))
			.catch(() => (key = null));
		getLocations()
			.then((l) => (locations = l))
			.catch(() => (listError = true));
		getMeta()
			.then((m) => (meta = m))
			.catch(() => {}); // the labels just lose their numbers
		if (support === 'ok') {
			currentSubscription()
				.then(async (s) => {
					on = s !== null;
					const saved = on ? await savedChoices() : null;
					if (saved) {
						picked = saved.locations;
						types = saved.types;
					}
				})
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
			message = `This device couldn't sign up with its push service (${(e as Error).message}). Try again in a moment.`;
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

	// While alerts are on, a change saves itself a moment after the last tap.
	let saveState = $state<'idle' | 'saving' | 'saved' | 'failed'>('idle');
	let saveTimer: ReturnType<typeof setTimeout> | undefined;
	function queueSave() {
		if (!on) return;
		clearTimeout(saveTimer);
		if (!types.length) {
			saveState = 'idle';
			return;
		}
		saveState = 'saving';
		saveTimer = setTimeout(async () => {
			try {
				const res = await saveChoices(choices());
				saveState = res.ok ? 'saved' : 'failed';
				if (!res.ok) message = res.detail ?? 'Your changes couldn’t be saved. Try again.';
			} catch {
				saveState = 'failed';
				message = 'Your changes couldn’t be saved. Check your connection and try again.';
			}
		}, 600);
	}
	$effect(() => () => clearTimeout(saveTimer));
	// Alerts are written in the chosen units, so a change of units saves too.
	let lastUnits = untrack(() => prefs.units);
	$effect(() => {
		const u = prefs.units;
		if (u === lastUnits) return;
		lastUnits = u;
		untrack(queueSave);
	});
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
						onchange={() => {
							types = toggle(types, t);
							queueSave();
						}}
					/>
					{label}</label
				>
			{/each}
		</fieldset>
		<fieldset>
			<legend>For</legend>
			<label class="check"
				><input
					type="checkbox"
					checked={picked.length === 0}
					onchange={() => {
						picked = [];
						queueSave();
					}}
				/> Every location</label
			>
			{#each locations as l (l.id)}
				<label class="check"
					><input
						type="checkbox"
						checked={picked.includes(l.id)}
						onchange={() => {
							picked = toggle(picked, l.id);
							queueSave();
						}}
					/>
					{l.name}</label
				>
			{/each}
			{#if listError}
				<p class="faint small">Couldn’t load the location list; alerts cover every location.</p>
			{/if}
		</fieldset>
		{#if on}
			<p class="small faint autosave" aria-live="polite">
				{saveState === 'saving'
					? 'Saving…'
					: saveState === 'saved'
						? 'Changes saved.'
						: saveState === 'failed'
							? 'Not saved.'
							: !types.length
								? 'Pick at least one alert to save your changes.'
								: 'Changes save automatically.'}
			</p>
		{/if}
		<div class="actions">
			{#if !on}
				<button class="btn primary" disabled={busy || !types.length} onclick={enable}
					>Turn on alerts</button
				>
			{:else}
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
	.autosave {
		margin: 0 0 8px;
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
