<!-- The owner password form for the Manage page. -->
<script lang="ts">
	import { ApiError, login } from '../api';
	import type { Me } from '../types.gen';

	let { onSignedIn }: { onSignedIn: (me: Me) => void } = $props();

	let password = $state('');
	let error = $state<string | null>(null);
	let busy = $state(false);

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		if (!password || busy) return;
		busy = true;
		error = null;
		try {
			const me = await login(password);
			password = '';
			onSignedIn(me);
		} catch (err) {
			error =
				err instanceof ApiError
					? err.status === 401
						? 'That password isn’t right.'
						: err.message
					: 'Couldn’t reach the server. Check your connection and try again.';
		} finally {
			busy = false;
		}
	}
</script>

<form class="card login" onsubmit={submit}>
	<h2>Owner sign-in</h2>
	<p class="muted small">Enter the owner password set on the server to manage locations.</p>
	<label for="owner-password">Password</label>
	<input
		id="owner-password"
		type="password"
		autocomplete="current-password"
		bind:value={password}
		aria-invalid={error ? 'true' : undefined}
		aria-describedby={error ? 'owner-password-error' : undefined}
		required
	/>
	{#if error}<p id="owner-password-error" class="bad small" role="alert">{error}</p>{/if}
	<button class="btn primary" type="submit" disabled={busy || !password}>
		{busy ? 'Signing in…' : 'Sign in'}
	</button>
</form>

<style>
	.login {
		display: grid;
		gap: 8px;
		max-width: 420px;
	}
	h2 {
		margin: 0;
		font-size: 1.1rem;
	}
	p {
		margin: 0;
	}
	label {
		font-weight: 600;
		font-size: 0.9rem;
	}
	input {
		padding: 10px 12px;
		border-radius: 10px;
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--text);
		font: inherit;
	}
	.small {
		font-size: 0.85rem;
	}
	.bad {
		color: var(--temp);
	}
	button {
		justify-self: start;
	}
</style>
