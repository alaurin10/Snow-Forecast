import type { LocationSummary, OverviewRow, RunOut, Snapshot, TrendOut } from './types.gen';
import { session } from './session.svelte';

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

/** Cloudflare Access wants the viewer to log in again. */
export class SignInRequired extends ApiError {
	constructor() {
		super(401, 'Sign in again');
	}
}

async function request(path: string): Promise<Response> {
	// redirect: 'manual' turns an Access login redirect into an opaque response
	// we can recognise, instead of a CORS failure that looks like being offline.
	const r = await fetch(path, { headers: { Accept: 'application/json' }, redirect: 'manual' });
	const html = (r.headers.get('content-type') ?? '').includes('text/html');
	if (r.type === 'opaqueredirect' || (r.status >= 300 && r.status < 400) || (r.ok && html)) {
		session.signInNeeded = true;
		throw new SignInRequired();
	}
	return r;
}

async function get<T>(path: string): Promise<T> {
	const r = await request(path);
	if (!r.ok) {
		let detail = r.statusText;
		try {
			detail = ((await r.json()) as { detail?: string }).detail ?? detail;
		} catch {
			// not JSON
		}
		throw new ApiError(r.status, detail);
	}
	return (await r.json()) as T;
}

const snapshots = new Map<string, Promise<Snapshot>>();

export const getLocations = () => get<LocationSummary[]>('/api/locations');
export const getOverview = () => get<OverviewRow[]>('/api/overview');
export const getRuns = (limit = 20) => get<RunOut[]>(`/api/runs?limit=${limit}`);

export interface Health {
	status: 'ok' | 'stale' | 'no_data' | string;
	age_s: number | null;
	last_run: {
		id: number;
		status: string;
		finished_at: string;
		errors: number;
		api_weight: number;
	} | null;
}

/** /api/health answers 503 when data is stale or missing; that's still a valid answer. */
export async function getHealth(): Promise<Health> {
	const r = await request('/api/health');
	return (await r.json()) as Health;
}

export function getSnapshot(id: string, { fresh = false } = {}): Promise<Snapshot> {
	if (fresh || !snapshots.has(id)) {
		const p = get<Snapshot>(`/api/locations/${encodeURIComponent(id)}`);
		p.catch(() => snapshots.delete(id));
		snapshots.set(id, p);
	}
	return snapshots.get(id)!;
}

export const getTrend = (id: string) =>
	get<TrendOut>(`/api/locations/${encodeURIComponent(id)}/trend`);
