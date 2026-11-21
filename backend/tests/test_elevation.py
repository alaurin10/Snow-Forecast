"""The ground's height on the map's grid (elevation.py), and Net.found."""

from __future__ import annotations

import io
import re
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

from snowwatch.maps import elevation
from snowwatch.maps.geomet import Net
from snowwatch.maps.region import box_region
from snowwatch.maps.tiles_render import TILE, terrarium

REGION = box_region(46, -123, 48, -120, 600)  # ~0.4 km pixels


def encode(elev: np.ndarray) -> bytes:
    """A Terrarium PNG, as Mapterhorn serves (WebP there; the decoder reads either)."""
    v = elev.astype(np.float64) + 32768
    rgb = np.stack([v // 256, np.floor(v) % 256, np.floor((v % 1) * 256)], axis=-1)
    buf = io.BytesIO()
    Image.fromarray(rgb.astype(np.uint8), "RGB").save(buf, "PNG")
    return buf.getvalue()


class Tiles(Net):
    """Mapterhorn: a tile's height is 100 m × its column within the zoom, flat across it;
    tiles in `sea` answer 404 and those in `down` fail."""

    def __init__(self, sea: set[int] = frozenset(), down: set[int] = frozenset()) -> None:  # type: ignore[assignment]
        self.sea, self.down = sea, down
        self.asked: list[str] = []

    def found(self, url: str, tries: int = 3) -> tuple[bytes | None, bool]:
        self.asked.append(url)
        m = re.search(r"/(\d+)/(\d+)/(\d+)\.webp$", url)
        assert m
        x = int(m[2])
        if x in self.sea:
            return None, True
        if x in self.down:
            return None, False
        return encode(np.full((TILE, TILE), 100.0 * x)), False


def test_terrarium_round_trip() -> None:
    elev = np.array([[0.0, 1234.5], [-20.0, 4392.25]] * 2).reshape(4, 2)
    got = terrarium(encode(elev))
    assert got is not None and np.allclose(got, elev, atol=0.01)


def test_zoom_has_a_few_tile_pixels_to_each_region_pixel() -> None:
    from snowwatch.maps.region import WEST, region_for

    assert elevation.zoom_for(region_for([], WEST)) == 6  # ~2.5 km pixels, ~1.2 km tiles
    assert elevation.zoom_for(REGION) == elevation.MAX_ZOOM  # small box: capped


def test_each_pixel_is_the_mean_of_the_ground_under_it(tmp_path: Path) -> None:
    net = Tiles()
    elev = elevation.region_elevation(net, REGION, tmp_path)
    assert elev is not None and elev.shape == (REGION.height, REGION.width)
    z = elevation.zoom_for(REGION)
    lons, _ = REGION.lonlats()
    # Each pixel: the height of the tile column it lies in (pixels are much smaller here).
    cols = ((lons + 180) / 360 * 2**z).astype(int)
    inside = np.abs((lons + 180) / 360 * 2**z - cols - 0.5) < 0.45  # off the tiles' seams
    assert elev[0, inside].tolist() == pytest.approx((100.0 * cols[inside]).tolist())
    assert (elev == elev[0]).all()  # flat north to south
    # Kept: the next job reads it from disk.
    again = Tiles()
    assert np.array_equal(elevation.region_elevation(again, REGION, tmp_path), elev)
    assert again.asked == []


def test_sea_is_sea_level_but_a_failing_source_is_nothing(tmp_path: Path) -> None:
    z = elevation.zoom_for(REGION)
    lons, _ = REGION.lonlats()
    first = int((lons[0] + 180) / 360 * 2**z)
    elev = elevation.build(Tiles(sea={first}), REGION)
    assert elev is not None and elev[0, 0] == 0 and elev[0, -1] > 0
    # Most tiles failing (not 404): try again next time, and keep nothing.
    xs = set(range(first, first + 8))
    assert elevation.region_elevation(Tiles(down=xs), REGION, tmp_path) is None
    assert not list(tmp_path.iterdir())


def test_found_tells_a_404_from_a_failure() -> None:
    def answer(req: httpx.Request) -> httpx.Response:
        code = {"/ok": 200, "/none": 404, "/busy": 503, "/no": 403}[req.url.path]
        return httpx.Response(code, content=b"x" if code == 200 else b"")

    net = Net(httpx.Client(transport=httpx.MockTransport(answer)), sleep=lambda s: None)
    assert net.found("https://t/ok") == (b"x", False)
    assert net.found("https://t/none") == (None, True)
    assert net.found("https://t/busy") == (None, False)
    assert net.found("https://t/no") == (None, False)
