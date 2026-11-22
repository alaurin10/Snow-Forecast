// Downloads and unpacks precipitation frames off the main thread (./codec.ts): fetch,
// inflate, undo the row filter, and for a phone halve the radar's rate plane. The planes
// go back as transferred buffers, ready to upload as textures. The snow total's steps
// (./steps.ts) and the forecast clouds (./clouds.ts) come the same way.
import { parseClouds, type CloudPlanes } from './clouds';
import { halve, parse, type Planes } from './codec';
import { parseStep, type StepPlanes } from './steps';

export type AnyPlanes = Planes | StepPlanes | CloudPlanes;

export type LoadRequest =
	{ type: 'load'; id: number; url: string; half: boolean } | { type: 'cancel'; id: number };

export type LoadResponse =
	| { id: number; ok: true; planes: AnyPlanes }
	| { id: number; ok: false; error: string; aborted: boolean };

const aborts = new Map<number, AbortController>();

async function load(url: string, half: boolean, signal: AbortSignal): Promise<AnyPlanes> {
	const res = await fetch(url, { signal });
	if (!res.ok || !res.body) throw new Error(`frame ${res.status}`);
	const raw = await new Response(
		res.body.pipeThrough(new DecompressionStream('gzip'))
	).arrayBuffer();
	const bytes = new Uint8Array(raw);
	const step = parseStep(bytes);
	if (step) return step;
	const clouds = parseClouds(bytes);
	if (clouds) return clouds;
	const planes = parse(bytes);
	if (!planes) throw new Error('not a frame');
	return half ? halve(planes) : planes;
}

self.onmessage = (ev: MessageEvent<LoadRequest>) => {
	const msg = ev.data;
	if (msg.type === 'cancel') {
		aborts.get(msg.id)?.abort();
		return;
	}
	const abort = new AbortController();
	aborts.set(msg.id, abort);
	const post = (r: LoadResponse, transfer: Transferable[] = []) =>
		(self as unknown as Worker).postMessage(r, transfer);
	load(msg.url, msg.half, abort.signal)
		.then(
			(planes) =>
				post(
					{ id: msg.id, ok: true, planes },
					'step' in planes
						? [planes.area.buffer, planes.bands.buffer]
						: 'cloud' in planes
							? [planes.shares.buffer, planes.heights.buffer]
							: [planes.rate.buffer, planes.type.buffer]
				),
			(e: unknown) =>
				post({
					id: msg.id,
					ok: false,
					error: e instanceof Error ? e.message : String(e),
					aborted: abort.signal.aborted
				})
		)
		.finally(() => aborts.delete(msg.id));
};
