import type { LocationSummary, Snapshot, TrendOut } from './types.gen';

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

async function get<T>(path: string): Promise<T> {
	const r = await fetch(path, { headers: { Accept: 'application/json' } });
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
