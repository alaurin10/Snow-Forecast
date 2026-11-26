// 3D terrain on a phone: MapLibre draws the flat map into a texture for each terrain tile
// and lays it over the ground. Each texture is the terrain tile's size times a quality
// factor of 2: with our 512 px elevation tiles (drawn a zoom up, so 1024 px) that is
// 2048 x 2048 with mipmaps, about 21 MB of graphics memory a tile, and a phone tilted
// towards the horizon holds 10 to 14 of them (measured: over 300 MB, on top of the radar's
// frames and the map's own tiles). Past what the phone allows, the browser drops the map's
// graphics context and the map goes blank.
//
// At a factor of 1 the textures are 1024 x 1024 (about 5 MB), a quarter of the memory.
// The base map and overlay tiles are 256 px tiles shown at 512 px, so they have no more
// detail than that to give; only lines drawn into the drape (contours, runs) soften a little.
// Labels and markers are drawn over the terrain, not into it, and stay sharp.
//
// MapLibre has no option for this: it reads the factor once, when the terrain is set, into
// its render-to-texture's `rttSize`. We change that field after each setTerrain. If a
// MapLibre update renames it, this does nothing and says so in the console.
import type { Map as MlMap } from 'maplibre-gl';

/** Texels per terrain tile pixel in the drape on a phone (MapLibre's own is 2). */
export const LEAN_DRAPE = 1;

interface Internals {
	terrain?: { tileManager?: { tileSize?: number; releaseAllRTT?: () => void } } | null;
	painter?: { renderToTexture?: { rttSize?: number } | null };
}

/**
 * Draw the 3D drape at `factor` texels per terrain tile pixel. Call right after
 * `map.setTerrain(...)` (each call makes a new render-to-texture at MapLibre's factor).
 * Returns whether it took.
 */
export function setDrapeQuality(map: MlMap, factor = LEAN_DRAPE): boolean {
	const m = map as unknown as Internals;
	const tiles = m.terrain?.tileManager;
	const rtt = m.painter?.renderToTexture;
	if (!rtt || typeof rtt.rttSize !== 'number' || typeof tiles?.tileSize !== 'number') {
		console.warn('3D terrain: MapLibre changed, drapes stay at full size');
		return false;
	}
	const size = Math.max(256, Math.round(tiles.tileSize * factor));
	if (rtt.rttSize === size) return true;
	rtt.rttSize = size;
	// Any tile already drawn at the old size is drawn again at the new one.
	tiles.releaseAllRTT?.();
	return true;
}
