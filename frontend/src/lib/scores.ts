// The forecast scorecard's words: what each source is called, and which has been closest.
import { MODEL_NAMES } from './models';
import type { VerificationOut, VerificationRow, WaterRow } from './types.gen';

const NAMES: Record<string, string> = {
	cons: 'Consensus (model snowfall, 7:1)',
	cons_slr: 'Consensus (temperature-based depth)',
	cons_col: 'Consensus (column snow ratio)',
	cons_wb: 'Consensus (rain and snow split by wet-bulb)',
	cons_settled: 'Consensus as settled snow',
	stn_settled: 'At the station’s elevation, as settled snow',
	stn_cons: 'Consensus at the station’s elevation',
	ens_p50: 'Ensemble median (7:1)'
};
const SHORT: Record<string, string> = {
	cons: 'the 7:1 consensus',
	cons_slr: 'the consensus',
	cons_col: 'the column-ratio consensus',
	cons_wb: 'the wet-bulb consensus',
	cons_settled: 'the settled-snow consensus',
	stn_settled: 'the forecast at the station',
	stn_cons: 'the forecast at the station',
	ens_p50: 'the ensemble median'
};

/** A source's full name, as the scorecard's rows show it. */
export const sourceName = (source: string): string =>
	NAMES[source] ?? MODEL_NAMES[source] ?? source;

/** A source's name inside a sentence ("GFS", "the consensus"). */
export const sourceShort = (source: string): string =>
	SHORT[source] ?? MODEL_NAMES[source] ?? source;

/** The source with the smallest average miss, among those scored on enough days. */
export function closest(rows: VerificationRow[], minDays = 7): VerificationRow | null {
	const scored = rows.filter((r) => r.mae_cm !== null && r.n >= minDays);
	if (!scored.length) return null;
	return scored.reduce((best, r) => (r.mae_cm! < best.mae_cm! ? r : best));
}

/** The consensus row the app's snow totals use. */
export const headlineRow = (data: VerificationOut): VerificationRow | null =>
	data.rows.find((r) => r.source === (data.headline ?? 'cons')) ?? null;

/** Days the forecast at the station needs before the charts lead with it. */
export const STATION_MIN_DAYS = 7;

/** The first of these sources that has a row; one at the station (`stn_…`) needs a week. */
function firstScored<T extends { source: string; n: number }>(
	rows: T[],
	sources: string[]
): T | null {
	for (const s of sources) {
		const r = rows.find((x) => x.source === s);
		if (r && (!s.startsWith('stn_') || r.n >= STATION_MIN_DAYS)) return r;
	}
	return null;
}

/** The row the depth chart scores: the forecast at the station as settled snow once it
 * has a week, else the mid band's settled snow, else the app's own. */
export const depthRow = (data: VerificationOut): VerificationRow | null =>
	firstScored(data.rows, ['stn_settled', 'cons_settled']) ?? headlineRow(data);

/** The precipitation row the chart scores: at the station once it has a week, else mid. */
export const waterRow = (data: VerificationOut): WaterRow | null =>
	firstScored(data.water_rows ?? [], ['stn_cons', 'cons']);

/** A precipitation source's name: the consensus says where it is. */
export const waterSourceName = (source: string): string =>
	source === 'cons' ? 'Consensus at mid-mountain' : sourceName(source);

/** The source whose precipitation has been closest, among those scored on enough days. */
export function closestWater(rows: WaterRow[], minDays = 7): WaterRow | null {
	const scored = rows.filter((r) => r.mae_mm !== null && r.n >= minDays);
	if (!scored.length) return null;
	return scored.reduce((best, r) => (r.mae_mm! < best.mae_mm! ? r : best));
}

/** Which depth method has been closer, or null when either is missing. */
export function closerMethod(data: VerificationOut): string | null {
	const raw = data.rows.find((r) => r.source === 'cons');
	const slr = data.rows.find((r) => r.source === 'cons_slr');
	if (!raw || !slr || raw.mae_cm === null || slr.mae_cm === null) return null;
	if (Math.abs(raw.mae_cm - slr.mae_cm) < 0.5) return 'about the same';
	return slr.mae_cm < raw.mae_cm ? 'temperature-based depth is closer' : 'model snowfall is closer';
}
