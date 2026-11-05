// The Calendar's sequential snow ramp: five steps of one blue, validated as an
// ordinal ramp in both themes (light gets darker with more snow; dark gets
// lighter). Bucket edges are in cm (1, 3, 6, 12 in) so colors don't change with
// the unit toggle.
export const EDGES_CM = [0.25, 2.54, 7.62, 15.24, 30.48];

/** 0 = no snow (neutral cell), 1–5 = ramp step. */
export function bucket(cm: number | null | undefined): number {
	if (cm === null || cm === undefined || cm < EDGES_CM[0]) return 0;
	let b = 1;
	for (let i = 1; i < EDGES_CM.length; i++) if (cm >= EDGES_CM[i]) b = i + 1;
	return b;
}

/** Print the number in cells of at least 1 in (2.54 cm). */
export const labelled = (cm: number | null | undefined): boolean => (cm ?? 0) >= 2.54;
