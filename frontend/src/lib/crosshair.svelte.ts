// One crosshair shared by every hourly chart. It holds the index into the
// hourly arrays; index 0 is the current hour, where it rests.
class Crosshair {
	index = $state(0);
	active = $state(false);

	set(i: number) {
		this.index = i;
		this.active = true;
	}

	reset() {
		this.index = 0;
		this.active = false;
	}
}

export const crosshair = new Crosshair();
