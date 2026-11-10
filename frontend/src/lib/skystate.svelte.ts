// Which sky the backdrop shows. The layout sets `home` (the first location's weather
// now); a location page sets `page` to its own sky while it is open.
import { DEFAULT_SKY, type SkyState } from './sky';

class SkyStore {
	home = $state<SkyState>(DEFAULT_SKY);
	page = $state<SkyState | null>(null);

	get current(): SkyState {
		return this.page ?? this.home;
	}
}

export const skyState = new SkyStore();
