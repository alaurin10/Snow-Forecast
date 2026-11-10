// The open location's sections (Forecast, Models, Backcountry, Observed). The location
// page owns them; on desktop the left rail shows them under that location, on phones
// and tablets the page shows them as tabs. Both read and set the same state.
export type Section = 'forecast' | 'models' | 'backcountry' | 'observed';

export const SECTION_NAMES: Record<Section, string> = {
	forecast: 'Forecast',
	models: 'Models',
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
