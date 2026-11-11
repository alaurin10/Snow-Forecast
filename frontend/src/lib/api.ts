import type {
	AvalancheView,
	BudgetOut,
	ConcernOut,
	CatalogItem,
	JobOut,
	Location,
	LocationSummary,
	LookupStatus,
	MapWindOut,
	Me,
	MetaOut,
	OverviewRow,
	StatusOut,
	VerificationOut,
	ZonesOut,
	ResolveIn,
	ResolveOut,
	RunOut,
	SaveOut,
	Snapshot,
	TrendOut
} from './types.gen';

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

function request(path: string, init: RequestInit = {}): Promise<Response> {
	return fetch(path, {
		...init,
		headers: { Accept: 'application/json', ...(init.headers ?? {}) }
	});
}

async function get<T>(path: string, init: RequestInit = {}): Promise<T> {
	const r = await request(path, init);
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
// The overview feeds both the page and the desktop rail; one copy serves both for a
// minute (a page reload or a new forecast run is the only thing that changes it).
let overview: { at: number; p: Promise<OverviewRow[]> } | null = null;
export function getOverview(): Promise<OverviewRow[]> {
	if (!overview || Date.now() - overview.at > 60_000) {
		const p = get<OverviewRow[]>('/api/overview');
		p.catch(() => (overview = null));
		overview = { at: Date.now(), p };
	}
	return overview.p;
}
/** Every location's loading roses, for the map's wind-effect layer. */
export const getMapWind = () => get<MapWindOut>('/api/map/wind');
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

// Avalanche forecasts expire on the clock, so a cached copy lives one minute.
let avalanche: { at: number; p: Promise<Record<string, AvalancheView>> } | null = null;
export function getAvalanche(): Promise<Record<string, AvalancheView>> {
	if (!avalanche || Date.now() - avalanche.at > 60_000) {
		const p = get<Record<string, AvalancheView>>('/api/avalanche');
		p.catch(() => (avalanche = null));
		avalanche = { at: Date.now(), p };
	}
	return avalanche.p;
}

/** Every avalanche forecast zone in the map's box, with expiry applied (cache: a minute). */
export const getAvalancheZones = () => get<ZonesOut>('/api/avalanche/zones.geojson');

/** The concern index's settings, or null when the server has it off (HAZARD_INDEX). */
export async function getConcern(): Promise<ConcernOut | null> {
	try {
		return await get<ConcernOut>('/api/map/concern');
	} catch (e) {
		if (e instanceof ApiError && e.status === 404) return null;
		throw e;
	}
}

export const getVerification = (id: string) =>
	get<VerificationOut>(`/api/locations/${encodeURIComponent(id)}/verification`);

export const getStatus = () => get<StatusOut>('/api/status');

// Version and server numbers; they don't change while the page is open.
let meta: Promise<MetaOut> | null = null;
export function getMeta(): Promise<MetaOut> {
	if (!meta) {
		meta = get<MetaOut>('/api/meta');
		meta.catch(() => (meta = null));
	}
	return meta;
}

// --- Owner sign-in and the Manage page ---

const send = <T>(method: string, path: string, body?: unknown) =>
	get<T>(path, {
		method,
		headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});

export const getMe = () => get<Me>('/api/me');
export const login = (password: string) => send<Me>('POST', '/api/auth/login', { password });
export const logout = () => send<Me>('POST', '/api/auth/logout');
export const adminLocations = () => get<Location[]>('/api/admin/locations');
export const adminLookups = () => get<LookupStatus>('/api/admin/lookups');
export const refreshLookups = () => send<JobOut>('POST', '/api/admin/lookups/refresh');
export const searchCatalog = (q: string) =>
	get<CatalogItem[]>(`/api/admin/catalog/search?q=${encodeURIComponent(q)}`);
export const resolveLocation = (body: ResolveIn) =>
	send<ResolveOut>('POST', '/api/admin/locations/resolve', body);
export const createLocation = (loc: Location) => send<SaveOut>('POST', '/api/admin/locations', loc);
export const updateLocation = (loc: Location) =>
	send<SaveOut>('PUT', `/api/admin/locations/${encodeURIComponent(loc.id)}`, loc);
export const archiveLocation = (id: string) =>
	send<{ ok: boolean }>('DELETE', `/api/admin/locations/${encodeURIComponent(id)}`);
export const reorderLocations = (ids: string[]) =>
	send<{ ok: boolean }>('PUT', '/api/admin/locations/order', ids);
export const refreshLocation = (id: string) =>
	send<JobOut>('POST', `/api/admin/locations/${encodeURIComponent(id)}/refresh`);
export const getJob = (id: number) => get<JobOut>(`/api/admin/jobs/${id}`);
export const getBudget = () => get<BudgetOut>('/api/admin/budget');

/** Poll a job until it's done or failed, ~3 minutes pass, or `signal` aborts (the page
 * was left). Returns the job as last seen, which may still be queued or running. */
export async function waitForJob(
	id: number,
	onUpdate?: (j: JobOut) => void,
	signal?: AbortSignal
): Promise<JobOut> {
	let j = await getJob(id);
	for (let i = 0; i < 90; i++) {
		if (signal?.aborted) break;
		onUpdate?.(j);
		if (j.status === 'done' || j.status === 'failed') return j;
		await new Promise((r) => setTimeout(r, 2000));
		if (signal?.aborted) break;
		j = await getJob(id);
	}
	return j;
}
