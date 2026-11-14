// The open location's sections (Forecast, Confidence, Backcountry, Observed). The
// location page owns them and shows them as its tabs on every screen; the shell's keys
// 1–4 pick one, and the rail marks which location is open. All read and set the same state.
export type Section = 'forecast' | 'confidence' | 'backcountry' | 'observed';

export const SECTION_NAMES: Record<Section, string> = {
	forecast: 'Forecast',
	confidence: 'Confidence',
	backcountry: 'Backcountry',
	observed: 'Observed'
};

class Sections {
	/** The location whose page is open, or null on other pages. */
	id = $state<string | null>(null);
	list = $state<Section[]>([]);
	tab = $state<Section>('forecast');
}

export const sections = new Sections();
