"""Milestone 2 of the map: our own HRRR, NBM, the RDPS/GDPS extended timeline, and snow
totals to 10 days."""

from __future__ import annotations

import io
import urllib.parse
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from snowwatch.config import SlrBand
from snowwatch.maps import blend, grib, totals
from snowwatch.maps.geomet import Grid, Net, iso_ts, on_region, prune_wcs_cache, ts_iso, wcs_grid
from snowwatch.maps.palette import (
    MIX,
    MIX_T,
    NONE,
    RAIN,
    RAIN_T,
    SNOW,
    SNOW_T,
    hex_rgb,
    paint_typed,
)
from snowwatch.maps.region import box_region
from snowwatch.maps.render import SPLIT_SOFT_MM, Renderer
from snowwatch.maps.sources import hrrr, nbm, rdps_gdps
from snowwatch.maps.sources.nbm import Nbm

FIXTURES = Path(__file__).parent / "fixtures" / "grib"
CSNOW = FIXTURES / "hrrr_20261110t14z_f01_csnow.grib2"
APCP = FIXTURES / "hrrr_20261110t14z_f01_apcp.grib2"
H = 3600
T0 = 1_800_000_000 - 1_800_000_000 % (6 * H)  # a synoptic hour

rain = [hex_rgb(c) for _, c in RAIN]
snow = [hex_rgb(c) for _, c in SNOW]
mix = [hex_rgb(c) for _, c in MIX]

BANDS = [
    SlrBand(min_c=-0.556, ratio=8, label="Heavy & wet"),
    SlrBand(min_c=-3.333, ratio=11, label="Average"),
    SlrBand(min_c=None, ratio=17, label="Dry & fluffy"),
]


def resp(text: str = "", content: bytes = b"", ctype: str = "") -> Any:
    return type("R", (), {"text": text, "content": content, "headers": {"content-type": ctype}})()


# ---- Painting -------------------------------------------------------------------------


def test_paint_typed_uses_each_ramp() -> None:
    rate = np.array([[0.05, 0.6, 2.5, 3.5, 12.0, np.nan]], np.float32)
    kinds = np.array([[SNOW_T, SNOW_T, MIX_T, SNOW_T, RAIN_T, RAIN_T]], np.uint8)
    out = paint_typed(rate, kinds)
    assert out[0, 0, 3] == 0  # below the first step
    assert tuple(out[0, 1, :3]) == snow[1]
    assert tuple(out[0, 2, :3]) == mix[1]
    assert tuple(out[0, 3, :3]) == snow[4]
    assert tuple(out[0, 4, :3]) == rain[5]
    assert out[0, 5, 3] == 0  # no data


# ---- GRIB: NBM's probability messages share the plain name ----------------------------


def test_find_skips_probability_and_percentile_messages() -> None:
    idx = (
        "30:100:d=2026111012:APCP:surface:234-240 hour acc fcst:prob >0.254:prob fcst 255/255\n"
        "49:200:d=2026111012:APCP:surface:234-240 hour acc fcst:\n"
        "88:300:d=2026111012:ASNOW:surface:2-3 hour acc@(fcst,dt=1 hour),missing=0:1% level\n"
        "103:400:d=2026111012:ASNOW:surface:2-3 hour acc fcst:\n"
        "104:500:d=2026111012:TMP:2 m above ground:3 hour fcst:\n"
    )
    entries = grib.parse_idx(idx)
    apcp = grib.find(entries, nbm.pattern("APCP", 234, 240))
    assert apcp is not None and apcp.start == 200 and apcp.end == 299
    asnow = grib.find(entries, nbm.pattern("ASNOW", 2, 3))
    assert asnow is not None and asnow.start == 400
    assert entries[0].extra.startswith("prob")


def test_messages_are_cached_on_disk(tmp_path: Path) -> None:
    msg = CSNOW.read_bytes()
    calls = {"idx": 0, "range": 0}

    class Files(Net):
        def __init__(self) -> None:
            pass

        def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
            calls["idx"] += 1
            return resp("1:0:d=2026111014:CSNOW:surface:1 hour fcst:\n")

        def range(self, url: str, start: int, end: int | None, tries: int = 3) -> bytes | None:
            calls["range"] += 1
            return msg

    net = Files()
    assert grib.fetch_messages(net, "https://x/f", [":CSNOW:", ":NOPE:"], tmp_path) == [msg, None]
    assert grib.fetch_messages(net, "https://x/f", [":CSNOW:"], tmp_path) == [msg]
    assert calls == {"idx": 1, "range": 1}  # the second time from disk
    old = 0
    for p in tmp_path.glob("*.grib2"):
        import os

        os.utime(p, (old, old))
    assert grib.prune_cache(tmp_path) == 1 and not list(tmp_path.glob("*.grib2"))
    assert grib.on_region(None, box_region(40, -120, 45, -110, 10)) is None
    assert grib.on_region(b"GRIBjunk", box_region(40, -120, 45, -110, 10)) is None


# ---- HRRR -----------------------------------------------------------------------------


def test_hrrr_type_flags() -> None:
    one = np.ones((1, 5), np.float32)
    zero = np.zeros((1, 5), np.float32)
    csnow = np.array([[1, 0, 1, 0, 0]], np.float32)
    crain = np.array([[0, 1, 1, 0, 0]], np.float32)
    cfrzr = np.array([[0, 0, 0, 1, 0]], np.float32)
    k = hrrr.kinds(csnow, crain, cfrzr, zero)
    assert k[0].tolist() == [SNOW_T, RAIN_T, MIX_T, MIX_T, NONE]
    assert hrrr.kinds(zero, zero, zero, one)[0].tolist() == [MIX_T] * 5
    # A wet pixel without a type takes its neighbour's, else rain; dry pixels have none.
    types = np.zeros((1, 30), np.uint8)
    types[0, 0] = SNOW_T
    wet = np.ones((1, 30), bool)
    wet[0, 29] = False
    filled = blend.fill_kinds(types, wet)
    assert filled[0, 3] == SNOW_T and filled[0, 20] == RAIN_T and filled[0, 29] == NONE


def test_hrrr_slots_take_the_newest_run() -> None:
    now = T0 + 2 * H + 600  # two hours after a synoptic run

    class Bucket(Net):
        def __init__(self) -> None:
            pass

        def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
            assert params is not None
            run_h = int(params["prefix"].split(".t")[1][:2])
            if run_h == (T0 // H) % 24:  # the synoptic run: to 48 h
                hours = range(0, 49)
            elif run_h == (T0 // H + 1) % 24:  # the next hourly run: to 18 h
                hours = range(0, 19)
            else:  # the newest is still arriving
                hours = range(0, 3) if run_h == (T0 // H + 2) % 24 else range(0)
            keys = "".join(
                f"<Key>{params['prefix']}{h:02d}.grib2.idx</Key>"
                f"<Key>{params['prefix']}{h:02d}.grib2</Key>"
                for h in hours
            )
            return resp(keys)

    slots = hrrr.slots(Bucket(), now)
    assert slots[T0 + 3 * H] == (T0 + 2 * H, 1)
    assert slots[T0 + 4 * H] == (T0 + 2 * H, 2)
    assert slots[T0 + 5 * H] == (T0 + H, 4)
    assert slots[T0 + 30 * H] == (T0, 30)
    assert max(slots) == T0 + 48 * H
    assert hrrr.file_url(T0, 7).endswith(f"conus/hrrr.t{(T0 // H) % 24:02d}z.wrfsfcf07.grib2")


def test_hrrr_draws_a_real_hour(tmp_path: Path) -> None:
    """The fixture hour (14 UTC run, 1 hour ahead): APCP and CSNOW are real messages."""
    msgs = {":APCP:": APCP.read_bytes(), ":CSNOW:": CSNOW.read_bytes()}

    class Files(Net):
        def __init__(self) -> None:
            pass

        def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
            return resp(
                "1:0:d=2026111014:APCP:surface:0-1 hour acc fcst:\n"
                "2:1000000:d=2026111014:CSNOW:surface:1 hour fcst:\n"
                "3:2000000:d=2026111014:CRAIN:surface:1 hour fcst:\n"
            )

        def range(self, url: str, start: int, end: int | None, tries: int = 3) -> bytes | None:
            return msgs[":APCP:"] if start == 0 else msgs[":CSNOW:"] if start == 1000000 else None

    region = box_region(40, -125, 49, -110, 200)
    got = hrrr.fields(Files(), iso_ts("2026-11-10T14:00:00Z"), 1, region, tmp_path)
    assert got is not None
    apcp, k = got
    wet = np.nan_to_num(apcp) >= blend.TRACE_MM
    assert wet.any() and (k[wet] != NONE).all() and (k[~wet] == NONE).all()
    # Off HRRR's grid there is no data, which is not the same as dry.
    far = hrrr.fields(Files(), iso_ts("2026-11-10T14:00:00Z"), 1, box_region(10, -170, 15, -160, 8))
    assert far is not None and np.isnan(far[0]).all() and (far[1] == NONE).all()


# ---- NBM ------------------------------------------------------------------------------


def test_nbm_kinds_from_snow_share() -> None:
    apcp = np.array([[10, 10, 10, 10, 0.05]], np.float32)
    asnow = np.array([[0.15, 0.07, 0.03, 0.0, 0.01]], np.float32)  # metres
    apcp[0, 4] = 0.005  # under a trace: no type
    assert nbm.kinds(apcp, asnow)[0].tolist() == [SNOW_T, SNOW_T, MIX_T, RAIN_T, NONE]


def test_nbm_latest_run_needs_its_last_file() -> None:
    now = T0 + 13 * H  # T0 is 00, 06, 12 or 18 UTC

    class Bucket(Net):
        def __init__(self) -> None:
            self.asked: list[str] = []

        def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
            self.asked.append(url)
            # The newest synoptic run (T0 + 12 h) isn't complete yet.
            return None if f"t{(T0 // H + 12) % 24:02d}z" in url else resp("x")

    b = Bucket()
    assert nbm.latest_run(b, now, (0, 6, 12, 18)) == T0 + 6 * H
    assert all(u.endswith("f264.co.grib2.idx") for u in b.asked)
    assert nbm.latest_run(Bucket(), now, ()) is None


class FakeNbm(Nbm):
    """1 mm of water and 1 cm of snow an hour everywhere, in the sums NBM publishes; the
    snow level at `level` m and NBM's ratio 10:1 at every forecast hour."""

    def __init__(self, run: int, region: Any, level: float = 500.0) -> None:
        super().__init__(Net.__new__(Net), run, region)
        self.asked: list[tuple[int, int]] = []
        self.level = level
        self.fields: list[tuple[int, str]] = []

    def field(self, fhour: int, var: str, level: str) -> np.ndarray | None:
        self.fields.append((fhour, var))
        if fhour < 1 or fhour > nbm.LAST_H:
            return None
        value = {"SNOWLVL": self.level, "SNOWLR": 10.0}.get(var)
        if value is None:
            return None
        return np.full((self.region.height, self.region.width), value, np.float32)

    def sums(self, end: int, hours: int, vars_: list[str]) -> list[np.ndarray | None]:
        self.asked.append((end, hours))
        ok = (hours == 6 and end % 6 == 0) or (hours == 1 and end <= 48)
        if not ok or end > nbm.LAST_H:
            return [None] * len(vars_)
        shape = (self.region.height, self.region.width)
        per = {"APCP": 1.0, "ASNOW": 0.01}
        return [np.full(shape, per[v] * hours, np.float32) for v in vars_]


def test_nbm_snow_between_any_two_hours() -> None:
    region = box_region(40, -120, 45, -110, 4)
    fake = FakeNbm(T0, region)
    # 3 → 60: hourly to 6, whole blocks to 48, whole blocks to 60.
    cm = fake.snow_cm(3, 60)
    assert cm is not None and np.allclose(cm, 57)
    assert (4, 1) in fake.asked and (12, 6) in fake.asked and (60, 6) in fake.asked
    # Past 48 h, a block only partly inside counts in proportion.
    part = FakeNbm(T0, region).snow_cm(50, 57)
    assert part is not None and np.allclose(part, 7)
    assert FakeNbm(T0, region).snow_cm(258, 270) is None  # past the run's end
    got = FakeNbm(T0, region).precip(60, 6)
    assert got is not None and np.allclose(got[0], 6) and (got[1] == SNOW_T).all()
    assert FakeNbm(T0, region).precip(51, 3) is None  # NBM has no 3-hour sums


# ---- Totals ---------------------------------------------------------------------------


def test_window_ends() -> None:
    t0 = T0 + 4 * H  # not synoptic
    last = T0 + 218 * H
    ends = dict(totals.window_ends(t0, last))
    assert ends[12] == t0 + 12 * H and ends[48] == t0 + 48 * H
    assert ends[72] == T0 + 72 * H  # 76 h back to the synoptic hour before
    assert ends[168] == T0 + 168 * H
    assert 240 not in ends  # the models stop 214 h after t0, short of 90% of 10 days
    near = dict(totals.window_ends(t0, T0 + 228 * H))
    assert near[240] == T0 + 228 * H  # within 10%: kept, ending where the models do
    short = totals.window_ends(t0, t0 + 30 * H)
    assert short == [(12, t0 + 12 * H), (24, t0 + 24 * H), (48, t0 + 30 * H)]


def test_ratio_from_temperature() -> None:
    temp = np.array([[2.0, -1.0, -5.0, -20.0, np.nan]], np.float32)
    r = totals.ratio_grid(temp, BANDS)
    assert isinstance(r, np.ndarray) and r[0].tolist() == [8, 11, 17, 17, 10]
    assert totals.ratio_grid(None, BANDS) == 10


def test_totals_join_across_the_border() -> None:
    region = box_region(47, -125, 51, -115, 20)
    us = 1 - blend.north_weight(region)  # NBM everywhere it has data, south of the border
    assert us[0, 0] == 0 and us[-1, 0] == 1 and 0 < us[us.shape[0] // 2, 0] < 1
    n = np.full((region.height, region.width), 10, np.float32)
    s = np.full_like(n, 20)
    s[:, 0] = np.nan
    out = totals.join(n, s, us)
    assert out[0, 5] == 10 and out[-1, 5] == 20 and out[-1, 0] == 10
    column = out[:, 5]
    assert (np.diff(column) >= -1e-5).all() and 10 < column[region.height // 2] < 20
    assert totals.join(None, s, us) is s and totals.join(n, None, us) is n
    with pytest.raises(ValueError):
        totals.join(None, None, us)


def float_tiff(values: np.ndarray, lon0: float, lat0: float, d: float) -> bytes:
    from PIL import TiffImagePlugin

    im = Image.fromarray(values.astype(np.float32), "F")
    info = TiffImagePlugin.ImageFileDirectory_v2()
    info[33922] = (0.0, 0.0, 0.0, lon0, lat0, 0.0)
    info[33550] = (d, d, 0.0)
    buf = io.BytesIO()
    im.save(buf, "TIFF", tiffinfo=info)
    return buf.getvalue()


class ModelsNet(Net):
    """GeoMet with three runs: HRDPS to 48 h, RDPS to 84 h, GDPS to 240 h from T0.

    Each period snows 0.6 mm of water an hour everywhere, with no rain or ice. Snow water
    since each run began rises 1 mm an hour; the temperature is -1 °C (11:1) except
    GDPS, which has none (10:1). HRDPS's domain is the whole box unless `domain_rows`
    says how many rows from the top it covers."""

    def __init__(
        self, gdps: bool = True, domain_rows: int | None = None, snow_level: float = 500.0
    ) -> None:
        self.gdps = gdps
        self.domain_rows = domain_rows
        self.snow_level = snow_level
        self.coverages: list[str] = []
        self.maps: list[str] = []

    def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
        if params and params.get("request") == "GetCapabilities":
            layer = params["layer"]
            if layer.startswith("HRDPS"):
                end, step = 48, "PT1H"
            elif layer.startswith("RDPS"):
                end, step = 84, "PT3H" if "3h" in layer else "PT1H"
            elif layer.startswith("GDPS") and self.gdps:
                end, step = 240, "PT6H" if "6h" in layer else "PT3H"
            else:
                return None
            first = 6 if step == "PT6H" else 3 if step == "PT3H" else 1
            text = (
                f'<Dimension name="time" default="x">{ts_iso(T0 + first * H)}/'
                f"{ts_iso(T0 + end * H)}/{step}</Dimension>"
                f'<Dimension name="reference_time" default="{ts_iso(T0)}">x</Dimension>'
            )
            return resp(text)
        if "GetCoverage" in url:
            q = urllib.parse.parse_qs(url.split("?", 1)[1])
            cov = q["coverageId"][0]
            self.coverages.append(cov)
            assert q["DIM_REFERENCE_TIME"] == [ts_iso(T0)]
            assert q["geotiff:compression"] == ["Deflate"]
            value = self.value(cov, iso_ts(q["TIME"][0]))
            if value is None:
                return None
            body = float_tiff(np.full((40, 60), value, np.float32), -136.0, 58.0, 0.5)
            return resp(content=body, ctype="image/tiff")
        return None

    def value(self, cov: str, t: int) -> float | None:
        if cov.endswith(("_Snow-Accum", "_SN", "_Precip-Accum", "_PR")):
            return (t - T0) / H  # running snow water (and all water) since the run began
        if cov.endswith("SnowLevelHeight"):
            return self.snow_level
        if cov.endswith(("_TT", "AirTemp_2m")):
            return None if cov.startswith("GDPS") else -1.0
        span = 6 if "6h" in cov else 3 if "3h" in cov else 1
        if "Snow" in cov or "_SN_" in cov or "Precip" in cov:
            return 0.6 * span
        return 0.0  # rain, freezing rain, ice pellets

    def image(
        self, url: str, params: dict[str, str] | None = None, tries: int = 3
    ) -> np.ndarray | None:
        assert params is not None
        self.maps.append(params["layers"])
        h, w = int(params["height"]), int(params["width"])
        out = np.zeros((h, w, 4), np.uint8)
        out[: h if self.domain_rows is None else self.domain_rows] = (0, 0, 0, 255)
        return out


def test_north_totals_chain_the_models() -> None:
    region = box_region(44, -125, 54, -110, 30)
    net = ModelsNet()
    chain = [
        r
        for r in (
            rdps_gdps.run_of(net, m, m.accum)
            for m in (rdps_gdps.HRDPS, rdps_gdps.RDPS, rdps_gdps.GDPS)
        )
        if r is not None
    ]
    assert [r.end - T0 for r in chain] == [48 * H, 84 * H, 240 * H]
    t0 = T0 + 4 * H
    ends = [t0 + 12 * H, T0 + 72 * H, T0 + 168 * H]
    north = totals.north_totals(net, region, t0, ends, chain, BANDS)
    # 1 mm an hour: 11:1 while there are temperatures (HRDPS, RDPS), 10:1 after (GDPS).
    assert np.allclose(north.cm[ends[0]], 12 * 1.1)
    assert np.allclose(north.cm[ends[1]], 68 * 1.1)
    assert np.allclose(north.cm[ends[2]], 80 * 1.1 + 84 * 1.0, atol=0.05)
    assert north.runs == {"hrdps": ts_iso(T0), "rdps": ts_iso(T0), "gdps": ts_iso(T0)}
    assert "RDPS_10km_Snow-Accum" in net.coverages and "GDPS_15km_Snow-Accum" in net.coverages
    assert totals.north_totals(net, region, t0, [], chain, BANDS).cm == {}
    # Without GDPS the chain stops at 84 h.
    short = totals.north_totals(net, region, t0, ends, chain[:2], BANDS)
    assert set(short.cm) == set(ends[:2])


def test_south_totals_from_nbm() -> None:
    region = box_region(40, -120, 45, -110, 4)
    t0 = T0 + 4 * H
    ends = [t0 + 12 * H, T0 + 72 * H, T0 + 300 * H]
    south = totals.south_totals(FakeNbm(T0, region), t0, ends)
    assert np.allclose(south[ends[0]], 12) and np.allclose(south[ends[1]], 68)
    assert ends[2] not in south  # past the run's end
    assert totals.south_totals(None, t0, ends) == {}
    assert totals.south_totals(FakeNbm(t0 + H, region), t0, ends) == {}  # run after t0


def test_totals_render_both_sides_and_keep_the_numbers(tmp_path: Path, monkeypatch: Any) -> None:
    region = box_region(44, -125, 54, -110, 30)
    net = ModelsNet()
    monkeypatch.setattr(nbm, "latest_run", lambda net, now, cycles: T0)
    monkeypatch.setattr(Renderer, "_nbm", lambda self, region: FakeNbm(T0, region))
    now = T0 + 4 * H + 600
    r = Renderer(tmp_path / "precip", net, now=lambda: now, slr_bands=BANDS)
    ix = r.snow_totals(region)
    wins = [t["window"] for t in ix["totals"]]
    assert wins == [12, 24, 48, 72, 120, 168, 240]
    ten = ix["totals"][-1]
    assert ten["hours"] == 236 and ten["source"] == "hrdps+rdps+gdps+nbm"
    assert ten["runs"]["nbm"] == T0 and ten["runs"]["gdps"] == T0
    assert any("National Blend" in a for a in ix["attribution"])
    grid = np.load(tmp_path / "precip" / ".work" / "totals" / "24h.npy")
    assert grid.dtype == np.float16 and grid.shape == (region.height, region.width)
    # In Canada 24 mm at 11:1; in the US NBM's 24 cm.
    assert abs(float(grid[0, 5]) - 26.4) < 0.1 and abs(float(grid[-1, 5]) - 24) < 0.1
    # Nothing new: nothing recomputed.
    before = len(net.coverages)
    again = Renderer(tmp_path / "precip", net, now=lambda: now, slr_bands=BANDS).snow_totals(region)
    assert len(net.coverages) == before + 0 and [t["file"] for t in again["totals"]] == [
        t["file"] for t in ix["totals"]
    ]


# ---- The extended timeline ------------------------------------------------------------


def picture(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"))


def test_forecast_runs_to_ten_days(tmp_path: Path, monkeypatch: Any) -> None:
    region = box_region(44, -125, 54, -110, 30)
    net = ModelsNet()
    now = T0 + 4 * H + 600
    monkeypatch.setattr(hrrr, "slots", lambda net, now: {})
    monkeypatch.setattr(Renderer, "_nbm", lambda self, region: FakeNbm(T0, region))
    ix = Renderer(tmp_path, net, now=lambda: now).forecast(region)
    fr = ix["frames"]
    hourly = [f for f in fr if f["span_h"] == 1]
    three = [f for f in fr if f["span_h"] == 3]
    six = [f for f in fr if f["span_h"] == 6]
    assert hourly[-1]["t"] == T0 + 48 * H
    assert hourly[0]["src"]["south"] == "nbm"  # no HRRR: NBM's hourly fields
    assert [f["t"] - T0 for f in three] == [h * H for h in range(51, 85, 3)]
    assert [f["t"] - T0 for f in six] == [h * H for h in range(90, 241, 6)]
    assert {f["src"]["south"] for f in three} == {"nbm"}  # also NBM's block ending at 48 h
    assert six[-1]["src"] == {"north": "gdps", "south": "nbm"}
    # In Canada the model's 0.6 mm/h of snow; in the US NBM's 1 mm/h (a darker blue),
    # with nothing but those two shades down the column: no gap or third colour at the join.
    for f in (six[0], three[0]):
        img = picture(tmp_path / f["file"])
        assert tuple(img[0, 5, :3]) == snow[1] and tuple(img[-1, 5, :3]) == snow[2]
        column = {tuple(px[:3]) for px in img[:, 5]}
        assert column == {snow[1], snow[2]} and img[..., 3].min() == 255
    assert "RDPS_10km_FreezingRain-Accum-3h" in net.coverages
    assert "RDPS_10km_Precip-Accum3h" in net.coverages  # the other half of NBM's block
    assert "RDPS_10km_Snow-Accum1h" not in net.coverages  # HRDPS covers the box: no fill
    # Nothing new: nothing fetched or redrawn.
    before = (len(net.maps), len(net.coverages))
    again = Renderer(tmp_path, net, now=lambda: now).forecast(region)
    assert (len(net.maps), len(net.coverages)) == before
    assert [f["file"] for f in again["frames"]] == [f["file"] for f in fr]


def test_extended_frames_without_nbm_use_the_canadian_model(
    tmp_path: Path, monkeypatch: Any
) -> None:
    region = box_region(44, -125, 54, -110, 30)
    monkeypatch.setattr(hrrr, "slots", lambda net, now: {})
    monkeypatch.setattr(nbm, "latest_run", lambda net, now, cycles: None)
    ix = Renderer(tmp_path, ModelsNet(gdps=False), now=lambda: T0 + 600).forecast(region)
    ext = [f for f in ix["frames"] if f["span_h"] > 1]
    assert ext and all(f["src"] == {"north": "rdps", "south": "rdps"} for f in ext)
    assert max(f["t"] for f in ext) == T0 + 84 * H
    hourly = [f for f in ix["frames"] if f["span_h"] == 1]
    assert {f["south"] for f in hourly} == {""}


def test_hourly_frames_fade_from_hrdps_into_the_fill(tmp_path: Path, monkeypatch: Any) -> None:
    """HRDPS covers the top of the box only. With no US model, RDPS takes over below, and
    since both snow 0.6 mm/h the picture is one flat colour: the join can't be seen."""
    region = box_region(44, -125, 54, -110, 60)
    monkeypatch.setattr(hrrr, "slots", lambda net, now: {})
    monkeypatch.setattr(nbm, "latest_run", lambda net, now, cycles: None)
    net = ModelsNet(gdps=False, domain_rows=region.height // 2)
    ix = Renderer(tmp_path, net, now=lambda: T0 + 600).forecast(region)
    first = next(f for f in ix["frames"] if f["span_h"] == 1)
    assert first["src"] == {"north": "hrdps", "south": "rdps"}
    img = picture(tmp_path / first["file"])
    assert {tuple(px) for px in img.reshape(-1, 4)} == {(*snow[1], 255)}
    assert "RDPS_10km_Snow-Accum1h" in net.coverages


def test_hourly_frames_wait_for_hrdps(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(hrrr, "slots", lambda net, now: {})
    monkeypatch.setattr(nbm, "latest_run", lambda net, now, cycles: None)

    class NoDomain(ModelsNet):
        def image(self, url: str, params: Any = None, tries: int = 3) -> np.ndarray | None:
            return None

    region = box_region(44, -125, 54, -110, 30)
    # No domain picture and none kept from before: nothing is drawn (rather than guessed).
    assert Renderer(tmp_path / "a", NoDomain(), now=lambda: T0 + 600).forecast(region) == {}

    class NoSnow(ModelsNet):
        def value(self, cov: str, t: int) -> float | None:
            return None if cov == "HRDPS.CONTINENTAL.DIAG_SN_PT1H" else super().value(cov, t)

    ix = Renderer(tmp_path / "b", NoSnow(gdps=False), now=lambda: T0 + 600).forecast(region)
    assert [f for f in ix["frames"] if f["span_h"] == 1] == []  # tried again next time
    assert [f for f in ix["frames"] if f["span_h"] == 3]

    # A domain picture seen once is kept for when GeoMet won't draw it.
    r = Renderer(tmp_path / "c", ModelsNet(gdps=False), now=lambda: T0 + 600)
    assert r._hrdps_weight(region) is not None
    again = Renderer(tmp_path / "c", NoDomain(gdps=False), now=lambda: T0 + 600)
    w = again._hrdps_weight(region)
    assert w is not None and w.min() == 1


def test_nbm_six_hours_split_like_rdps(tmp_path: Path) -> None:
    """A 3-hour frame takes its share of NBM's 6-hour amount from RDPS's split; the two
    halves add up to the whole, and a dry RDPS splits it evenly."""
    region = box_region(44, -125, 54, -110, 20)
    shape = (region.height, region.width)

    class Split(ModelsNet):
        def value(self, cov: str, t: int) -> float | None:
            if cov == "RDPS_10km_Precip-Accum3h":
                return 6.0 if t == T0 + 51 * H else 2.0  # first half wetter
            return super().value(cov, t)

    net = Split()
    r = Renderer(tmp_path, net)
    run = rdps_gdps.run_of(net, rdps_gdps.RDPS, rdps_gdps.RDPS.snow)
    assert run is not None
    first_t, second_t, block_end = T0 + 51 * H, T0 + 54 * H, T0 + 54 * H
    first = r._share(run, first_t, block_end, np.full(shape, 6.0, np.float32), region)
    second = r._share(run, second_t, block_end, np.full(shape, 2.0, np.float32), region)
    assert isinstance(first, np.ndarray) and isinstance(second, np.ndarray)
    assert np.allclose(first + second, 1) and np.allclose(first, (6 + SPLIT_SOFT_MM) / 8.5)
    dry = r._share(run, first_t, block_end, np.zeros(shape, np.float32), region)

    class Dry(ModelsNet):
        def value(self, cov: str, t: int) -> float | None:
            return 0.0 if "Precip" in cov else super().value(cov, t)

    dry = Renderer(tmp_path / "dry", Dry())._share(
        run, first_t, block_end, np.zeros(shape, np.float32), region
    )
    assert np.allclose(dry, 0.5)
    # The other half isn't one of the run's times: an even split.
    assert r._share(run, T0 + 3 * H, T0 + 6 * H + 1, np.zeros(shape, np.float32), region) == 0.5


# ---- The blend itself -------------------------------------------------------------------


def test_feather_ramps_in_from_the_edge() -> None:
    valid = np.zeros((40, 60), bool)
    valid[:, 20:] = True  # the domain's edge runs down column 20
    w = blend.feather(valid, 10)
    row = w[20]
    assert (row[:20] == 0).all() and row[20] < 0.1 and row[30] == 1 and row[-1] == 1
    assert (np.diff(row[20:31]) > 0).all()  # rising all the way across the fade
    assert abs(row[25] - 0.5) < 0.1  # half way in, about half
    # The box's own edge is not a domain edge: full weight right up to it.
    assert w[0, 45] == 1 and w[-1, 59] == 1
    assert (blend.feather(np.ones((5, 5), bool), 3) == 1).all()
    assert (blend.feather(np.zeros((5, 5), bool), 3) == 0).all()


def test_feather_is_about_100_km() -> None:
    region = box_region(31, -134, 57, -102, 1700)
    px = blend.feather_px(region)
    assert 60 <= px <= 72  # ~1.5 km a pixel at the box's middle latitude


def test_mosaic_prefers_then_fades_then_fills() -> None:
    shape = (1, 7)
    first = blend.Layer(
        "first",
        np.array([[2, 2, 2, 2, np.nan, np.nan, np.nan]], np.float32),
        np.array([[1, 1, 0.5, 0.25, 0, 0, 0]], np.float32),
        np.full(shape, SNOW_T, np.uint8),
    )
    second = blend.Layer(
        "second",
        np.array([[4, 4, 4, 4, 4, 0, np.nan]], np.float32),
        1.0,
        np.array([[RAIN_T, RAIN_T, RAIN_T, RAIN_T, RAIN_T, NONE, NONE]], np.uint8),
    )
    m = blend.mosaic([first, second])
    # Well inside the first: only it. Then a weighted mean. Then the second alone.
    assert m.amount[0, :6].tolist() == [2, 2, 3, 3.5, 4, 0]
    assert np.isnan(m.amount[0, 6])  # neither has data
    # The type follows whichever source has the most weight (a tie stays with the first).
    assert m.kind[0].tolist() == [SNOW_T, SNOW_T, SNOW_T, RAIN_T, RAIN_T, NONE, NONE]
    assert abs(m.shares["first"] - 2.75 / 7) < 1e-6 and m.shares["second"] > 0
    with pytest.raises(ValueError):
        blend.mosaic([])


def test_mosaic_type_comes_from_a_source_that_has_one() -> None:
    dry = blend.Layer("a", np.zeros((1, 1), np.float32), 0.9, np.zeros((1, 1), np.uint8))
    wet = blend.Layer("b", np.full((1, 1), 5, np.float32), 1.0, np.full((1, 1), SNOW_T, np.uint8))
    m = blend.mosaic([dry, wet])
    assert abs(float(m.amount[0, 0]) - 0.5) < 1e-6 and m.kind[0, 0] == SNOW_T


def test_kinds_from_how_the_water_splits() -> None:
    total = np.array([[10, 10, 10, 10, 10, 0.001]], np.float32)
    snow_w = np.array([[9, 3, 1, 9, 0, 0.001]], np.float32)
    ice = np.array([[0, 0, 0, 4, 4, 0]], np.float32)
    k = blend.kinds_from_parts(total, snow_w, ice)
    # mostly snow; some snow → mix; hardly any → rain; snow with much ice → mix; ice → mix
    assert k[0].tolist() == [SNOW_T, MIX_T, RAIN_T, MIX_T, MIX_T, NONE]


def test_smooth_sampling_follows_a_slope_exactly() -> None:
    region = box_region(44, -124, 50, -114, 80)
    lon0, lat0, d = -126.0, 52.0, 0.5
    cols = lon0 + (np.arange(40) + 0.5) * d  # cell centres
    data = np.tile(cols.astype(np.float32) + 200, (30, 1))  # value = longitude + 200
    grid = Grid(data, lon0, lat0, d, d)
    lons, _ = region.lonlats()
    smooth = on_region(grid, region, smooth=True)
    assert np.allclose(smooth[10], lons + 200, atol=1e-3)
    blocky = on_region(grid, region)
    assert len(np.unique(blocky[10])) < len(np.unique(smooth[10]))
    # Off the grid: no data either way.
    far = Grid(data, 10.0, 52.0, d, d)
    assert np.isnan(on_region(far, region, smooth=True)).all()


def test_grids_are_cached_by_run(tmp_path: Path) -> None:
    region = box_region(44, -125, 54, -110, 30)
    net = ModelsNet()
    args = (net, "RDPS_10km_Snow-Accum3h", ts_iso(T0 + 51 * H), region)
    g = wcs_grid(*args, ref=ts_iso(T0), cache_dir=tmp_path)
    assert g is not None and len(net.coverages) == 1
    again = wcs_grid(*args, ref=ts_iso(T0), cache_dir=tmp_path)
    assert again is not None and np.array_equal(again.data, g.data) and len(net.coverages) == 1
    import os

    for p in tmp_path.glob("*.tif"):
        os.utime(p, (0, 0))
    assert prune_wcs_cache(tmp_path) == 1 and not list(tmp_path.glob("*.tif"))


def test_totals_fade_hrdps_into_rdps_at_its_domain_edge() -> None:
    region = box_region(44, -125, 54, -110, 30)
    shape = (region.height, region.width)

    class Wetter(ModelsNet):
        def value(self, cov: str, t: int) -> float | None:
            v = super().value(cov, t)
            return v * 2 if v is not None and cov == "RDPS_10km_Snow-Accum" else v

    net = Wetter()
    chain = [
        r
        for r in (rdps_gdps.run_of(net, m, m.accum) for m in (rdps_gdps.HRDPS, rdps_gdps.RDPS))
        if r is not None
    ]
    w = np.zeros(shape, np.float32)
    w[: region.height // 2] = 1  # HRDPS covers the top half
    t0, end = T0 + 6 * H, T0 + 18 * H
    out = totals.north_totals(net, region, t0, [end], chain, [], None, {"hrdps": w})
    # 12 mm at 10:1 where HRDPS covers, RDPS's 24 mm elsewhere.
    assert np.allclose(out.cm[end][0], 12) and np.allclose(out.cm[end][-1], 24)
    assert set(out.runs) == {"hrdps", "rdps"}


def section3(template: int, scan: int) -> bytes:
    """A GRIB2 message's first sections, just enough to carry a scanning mode."""
    sec1 = (21).to_bytes(4, "big") + b"\x01" + b"\0" * 16
    body = bytearray(81)
    body[0:4] = (81).to_bytes(4, "big")
    body[4] = 3
    body[12:14] = template.to_bytes(2, "big")
    body[64] = scan
    return b"GRIB" + b"\0" * 12 + sec1 + bytes(body) + (5).to_bytes(4, "big") + b"\x07"


def test_alternating_rows_are_unsnaked() -> None:
    assert grib.scanning_mode(section3(30, 0x50)) == 0x50  # NBM's Lambert grid
    assert grib.scanning_mode(section3(30, 0x40)) == 0x40
    assert grib.scanning_mode(section3(99, 0x50)) == 0  # a template we don't know
    assert grib.scanning_mode(CSNOW.read_bytes()) == 0x40  # HRRR: rows all one way
    v = np.array([[1, 2, 3], [6, 5, 4], [7, 8, 9]], np.float32)
    assert grib.unsnake(v).tolist() == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]


def test_no_ring_of_mix_between_snow_and_rain(tmp_path: Path) -> None:
    """Snow in the west half of a coarse model, rain in the east: between them the line is
    clean. A column of cells that really is half and half stays mix."""

    class Split(ModelsNet):
        def __init__(self, mixed_column: bool) -> None:
            super().__init__()
            self.mixed_column = mixed_column

        def get(self, url: str, params: dict[str, str] | None = None, tries: int = 3) -> Any:
            if "GetCoverage" not in url:
                return super().get(url, params, tries)
            cov = urllib.parse.parse_qs(url.split("?", 1)[1])["coverageId"][0]
            grid = np.zeros((40, 60), np.float32)
            snow_layer, rain_layer = "_Snow-" in cov, "_Rain-" in cov
            if snow_layer:
                grid[:, :30] = 6.0
            elif rain_layer:
                grid[:, 30:] = 6.0
            if self.mixed_column and (snow_layer or rain_layer):
                grid[:, 29:31] = 3.0
            return resp(content=float_tiff(grid, -136.0, 58.0, 0.5), ctype="image/tiff")

    region = box_region(44, -125, 54, -115, 200)  # the split is at 121°W
    lons, _ = region.lonlats()
    for mixed_column in (False, True):
        net = Split(mixed_column)
        run = rdps_gdps.run_of(net, rdps_gdps.GDPS, rdps_gdps.GDPS.snow)
        assert run is not None
        f = rdps_gdps.fields(net, run, T0 + 90 * H, region)
        assert f is not None and np.allclose(f.rate, 1.0)
        row = f.kind[region.height // 2]
        assert row[0] == SNOW_T and row[-1] == RAIN_T
        if mixed_column:
            assert (row[(lons > -121.2) & (lons < -120.8)] == MIX_T).all()
        else:
            assert MIX_T not in row
            edge = lons[np.argmax(row == RAIN_T)]
            assert abs(edge + 121) < 0.05  # the line sits where the model's cells meet
