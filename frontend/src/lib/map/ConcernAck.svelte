<!--
  Shown once per device before the concern index is first drawn: what it is, what it
  isn't, and an explicit "I understand" before anything shows. It takes the focus (the
  dialog itself, so neither answer is picked for you), keeps Tab inside, and Escape
  means Cancel.
-->
<script lang="ts">
	interface Props {
		caption: string;
		onaccept: () => void;
		oncancel: () => void;
	}

	let { caption, onaccept, oncancel }: Props = $props();
	let box = $state<HTMLDivElement>();

	$effect(() => {
		box?.focus();
	});

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			oncancel();
		} else if (e.key === 'Tab' && box) {
			const buttons = [...box.querySelectorAll<HTMLButtonElement>('button')];
			const first = buttons[0];
			const last = buttons[buttons.length - 1];
			const at = document.activeElement;
			if (e.shiftKey && (at === first || at === box)) {
				e.preventDefault();
				last.focus();
			} else if (!e.shiftKey && at === last) {
				e.preventDefault();
				first.focus();
			}
		}
	}
</script>

<div
	class="ack"
	role="alertdialog"
	aria-modal="true"
	aria-labelledby="ack-title"
	aria-describedby="ack-body"
	tabindex="-1"
	bind:this={box}
	{onkeydown}
>
	<h3 id="ack-title">Concern index (experimental)</h3>
	<div id="ack-body">
		<p><strong>{caption}</strong></p>
		<ul>
			<li>
				It is this app's own arithmetic: today's published danger for each elevation band, adjusted
				by slope angle, the bulletin's listed problems, likely wind loading and sun. No forecaster
				made it, and no avalanche center endorses it.
			</li>
			<li>
				Elevation bands use approximate treeline numbers. Slope comes from ~10 m terrain, so
				gullies, cornices, rollovers and trees don't show.
			</li>
			<li>
				It can't tell you a slope is safe. Read the full bulletin, and travel with the training and
				gear to make your own decisions.
			</li>
		</ul>
	</div>
	<div class="actions">
		<button class="btn" onclick={oncancel}>Cancel</button>
		<button class="btn primary" onclick={onaccept}>I understand</button>
	</div>
</div>

<style>
	.ack {
		position: absolute;
		top: 56px;
		left: 50%;
		transform: translateX(-50%);
		width: min(420px, calc(100% - 32px));
		max-height: calc(100% - 120px);
		overflow-y: auto;
		z-index: 1004;
		padding: 14px 16px;
		border-radius: 14px;
		background: var(--surface);
		border: 1px solid var(--border);
		box-shadow: var(--glass-shadow);
		color: var(--text);
		font-size: 0.85rem;
		display: grid;
		gap: 8px;
	}
	.ack:focus {
		outline: none;
	}
	.ack:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	h3 {
		margin: 0;
		font-size: 1rem;
	}
	p {
		margin: 0 0 6px;
	}
	ul {
		margin: 0;
		padding-left: 18px;
		display: grid;
		gap: 4px;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	/* Clear the floating tab bar on phones, so the last button can be tapped. */
	@media (max-width: 1099px) {
		.ack {
			max-height: calc(100% - 56px - 94px - env(safe-area-inset-bottom));
		}
	}
</style>
