// The forecast scorecard's words: what each source is called, and which has been closest.
import { MODEL_NAMES } from './models';
import type { VerificationOut, VerificationRow, WaterRow } from './types.gen';

const NAMES: Record<string, string> = {
	cons: 'Consensus (model snowfall, 7:1)',
	cons_slr: 'Consensus (temperature-based depth)',
	cons_settled: 'Consensus as settled snow',
	ens_p50: 'Ensemble median (7:1)'
};
const SHORT: Record<string, string> = {
	cons: 'the 7:1 consensus',
	cons_slr: 'the consensus',
	cons_settled: 'the settled-snow consensus',
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

/** The row the depth chart scores: the consensus as settled snow, else the app's own. */
export const depthRow = (data: VerificationOut): VerificationRow | null =>
	data.rows.find((r) => r.source === 'cons_settled') ?? headlineRow(data);

/** The consensus's precipitation against the gauge. */
export const waterRow = (data: VerificationOut): WaterRow | null =>
	data.water_rows?.find((r) => r.source === 'cons') ?? null;

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
