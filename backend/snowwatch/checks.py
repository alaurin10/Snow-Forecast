"""Live checks of every upstream source (`snowwatch check-sources`), written to docs/SOURCES.md.

Run it when a model or endpoint seems to have changed: the report shows which
model provides which variable, how far each model and ensemble reaches, the
snowfall ratio Open-Meteo uses, and the shape of every other endpoint.

`check-sources --local` checks a self-hosted Open-Meteo server the same way, and compares
the share of empty values in each column with the public API (or the saved fixtures when
the public API won't answer). `snowwatch openmeteo status` is the quick health check.
"""

from __future__ import annotations

import platform
import re
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from snowwatch.config import ForecastConfig
from snowwatch.http import LOCAL_SUFFIX, Fetcher, FetchError
from snowwatch.models import Location
from snowwatch.sources import avalanche_ca, avalanche_us, catalog, nws, snotel
from snowwatch.sources.base import Request, fetch
from snowwatch.sources.openmeteo import (
    ENSEMBLE_URL,
    FORECAST_URL,
    MULTI_HOURLY,
    SOURCE,
    UPPER_HOURLY,
    elevation_request,
    location_requests,
)

EXTRA_VARS = ["visibility", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high"]


def _hours_ahead(times: list[int], values: list[float | None], now: float) -> int:
    """Hours of non-null data from now on."""
    last = max((t for t, v in zip(times, values, strict=False) if v is not None), default=None)
    return 0 if last is None else max(0, round((last - now) / 3600))


def model_section(fetcher: Fetcher, loc: Location, models: list[str]) -> list[str]:
    mid = loc.band("mid")
    variables = [*MULTI_HOURLY, *EXTRA_VARS, *UPPER_HOURLY]
    req = Request(
        "check_models",
        SOURCE,
        FORECAST_URL,
        {
            "latitude": f"{mid.lat:g}",
            "longitude": f"{mid.lon:g}",
            "elevation": f"{loc.band('summit').elev_m:g}",
            "timezone": "auto",
            "timeformat": "unixtime",
            "forecast_days": "16",
            "hourly": ",".join(variables),
            "models": ",".join(models),
        },
    )
    data = fetch(fetcher, req)
    hourly = data["hourly"]
    times: list[int] = hourly["time"]
    now = time.time()
    lines = [
        f"### {loc.name} ({loc.country}), summit {loc.band('summit').elev_m:g} m",
        "",
        "| Model | Reach | Missing variables | snow cm per mm water (cold hours) |",
        "|---|---|---|---|",
    ]
    for m in models:
        reach = _hours_ahead(times, hourly.get(f"snowfall_{m}", []), now)
        missing = [
            v for v in variables if not any(x is not None for x in hourly.get(f"{v}_{m}", []))
        ]
        ratios = [
            s / p
            for s, p, t in zip(
                hourly.get(f"snowfall_{m}", []),
                hourly.get(f"precipitation_{m}", []),
                hourly.get(f"temperature_2m_{m}", []),
                strict=False,
            )
            if s is not None and p is not None and t is not None and p >= 0.3 and t <= -3
        ]
        ratio = f"{max(ratios):.2f} max, n={len(ratios)}" if ratios else "no cold precip"
        lines.append(
            f"| `{m}` | {reach} h | {', '.join(f'`{v}`' for v in missing) or 'none'} | {ratio} |"
        )
    return [*lines, ""]


def ensemble_section(fetcher: Fetcher, loc: Location, systems: list[str]) -> list[str]:
    mid = loc.band("mid")
    lines = ["| System | Members | Reach |", "|---|---|---|"]
    now = time.time()
    for system in systems:
        req = Request(
            "check_ens",
            SOURCE,
            ENSEMBLE_URL,
            {
                "latitude": f"{mid.lat:g}",
                "longitude": f"{mid.lon:g}",
                "elevation": f"{mid.elev_m:g}",
                "timezone": "auto",
                "timeformat": "unixtime",
                "forecast_days": "16",
                "hourly": "snowfall",
                "models": system,
            },
        )
        try:
            hourly = fetch(fetcher, req)["hourly"]
        except FetchError as e:
            lines.append(f"| `{system}` | error: {e} | |")
            continue
        keys = [k for k in hourly if k.startswith("snowfall")]
        reach = min(_hours_ahead(hourly["time"], hourly[k], now) for k in keys)
        lines.append(f"| `{system}` | {len(keys)} | {reach} h |")
    return [*lines, ""]


def _keys(d: Any) -> str:
    return ", ".join(f"`{k}`" for k in sorted(d)) if isinstance(d, dict) else type(d).__name__


def endpoint_section(fetcher: Fetcher, us_loc: Location | None) -> list[str]:
    out: list[str] = []

    def attempt(title: str, fn: Callable[[], list[str]]) -> None:
        out.extend([f"### {title}", ""])
        try:
            out.extend(fn())
        except (FetchError, KeyError, IndexError, TypeError) as e:
            out.append(f"Check failed: {e}")
        out.append("")

    def elevation() -> list[str]:
        d = fetch(fetcher, elevation_request([(46.935, -121.475), (48.518, -120.735)]))
        return [f"Two points in one call: `{d}`."]

    def nws_points() -> list[str]:
        assert us_loc is not None
        mid = us_loc.band("mid")
        p = fetch(fetcher, nws.points_request(mid.lat, mid.lon))["properties"]
        wanted = ["cwa", "gridId", "gridX", "gridY", "radarStation", "timeZone", "forecastZone"]
        return [f"`/points` for {us_loc.name}: " + ", ".join(f"`{k}`={p.get(k)}" for k in wanted)]

    def snotel_stations() -> list[str]:
        d = fetch(fetcher, snotel.stations_request("WA"))
        return [f"`stations?stationTriplets=*:WA:SNTL`: {len(d)} stations. Fields: {_keys(d[0])}."]

    def avalanche_org() -> list[str]:
        layer = fetch(fetcher, avalanche_us.map_layer_request())["features"]
        rated = [f for f in layer if (f["properties"].get("danger_level") or -1) >= 1]
        pick = (rated or layer)[0]
        prod = fetch(
            fetcher, avalanche_us.product_request(pick["properties"]["center_id"], str(pick["id"]))
        )
        return [
            f"Map layer: {len(layer)} zones ({len(rated)} rated now). "
            f"Properties: {_keys(pick['properties'])}.",
            "",
            f"Product for {pick['properties']['center_id']} zone {pick['id']} "
            f"(`{prod.get('product_type')}`): {_keys(prod)}. `danger`: `{prod.get('danger')}`.",
        ]

    def avcan() -> list[str]:
        areas = fetch(fetcher, avalanche_ca.areas_request())["features"]
        prods = fetch(fetcher, avalanche_ca.products_request())
        report = prods[0]["report"] if prods else {}
        sample = (report.get("dangerRatings") or [{}])[0]
        return [
            f"Areas: {len(areas)} polygons; feature fields {_keys(areas[0])}.",
            "",
            f"Products: {len(prods)}; product fields {_keys(prods[0]) if prods else '-'}; "
            f"report fields {_keys(report)}.",
            "",
            f"One `dangerRatings` entry: `{sample}`.",
        ]

    def ski_areas() -> list[str]:
        feats = fetch(fetcher, catalog.ski_areas_request())["features"]
        na = [
            f
            for f in feats
            if any(
                p.get("iso3166_1Alpha2") in ("US", "CA")
                for p in f["properties"].get("places") or []
            )
            and "downhill" in (f["properties"].get("activities") or [])
            and f["properties"].get("status") == "operating"
            and f["properties"].get("name")
        ]
        with_elev = [f for f in na if (f["properties"].get("statistics") or {}).get("maxElevation")]
        return [
            f"{len(feats)} ski areas worldwide; {len(na)} named, operating downhill areas in the "
            f"US and Canada, {len(with_elev)} with elevation statistics.",
            "",
            f"Properties: {_keys(feats[0]['properties'])}.",
        ]

    attempt("Open-Meteo elevation", elevation)
    if us_loc is not None:
        attempt("NWS", nws_points)
    attempt("SNOTEL (AWDB)", snotel_stations)
    attempt("avalanche.org", avalanche_org)
    attempt("Avalanche Canada", avcan)
    attempt("OpenSkiMap ski areas", ski_areas)
    return out


def build_report(fetcher: Fetcher, locs: list[Location], cfg: ForecastConfig) -> str:
    us = next((loc for loc in locs if loc.country == "US"), None)
    ca = next((loc for loc in locs if loc.country == "CA"), None)
    lines = [
        "# Data source check",
        "",
        f"Generated by `snowwatch check-sources` on "
        f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}. "
        "Reach counts hours of data from the time of the check.",
        "",
        "## Open-Meteo forecast models",
        "",
    ]
    for loc in (us, ca):
        if loc is not None:
            lines += model_section(fetcher, loc, cfg.models_for(loc.country))
    if ratios_note := _ratio_note(lines):
        lines += [ratios_note, ""]
    if us is not None:
        lines += ["## Open-Meteo ensembles", "", *ensemble_section(fetcher, us, cfg.ensembles)]
    lines += ["## Other endpoints", "", *endpoint_section(fetcher, us)]
    return "\n".join(lines).rstrip() + "\n"


def _ratio_note(lines: list[str]) -> str:
    vals = []
    for line in lines:
        if line.startswith("| `") and " max, n=" in line:
            vals.append(float(line.split("|")[4].split(" max")[0]))
    if not vals:
        return ""
    return (
        "Snowfall ratio: in cold hours, model snowfall tops out at "
        f"{statistics.median(vals):.2f} cm per mm of water, Open-Meteo's fixed 7:1 conversion."
    )


# --- The self-hosted Open-Meteo server ---------------------------------------------

LOCAL_HEADING = "## Self-hosted Open-Meteo server"
NULL_SHARE_POINTS = 5.0  # flag a column whose share of empty values differs by more
# The public data's model folders behind the models we use: each has a meta.json with its
# last run (`last_run_initialisation_time`, `last_run_availability_time`, Unix seconds).
# GEM's global and regional models moved to `cmc_gem_gdps_15km` and `cmc_gem_rdps_10km`
# (the old `cmc_gem_gdps` and `cmc_gem_rdps` stopped in May 2026).
DATA_URL = "https://openmeteo.s3.amazonaws.com/data"
MODEL_FOLDERS = (
    "ncep_hrrr_conus",
    "ncep_nbm_conus",
    "ncep_gfs013",
    "ncep_gfs025",
    "ecmwf_ifs025",
    "dwd_icon",
    "cmc_gem_gdps_15km",
    "cmc_gem_rdps_10km",
    "cmc_gem_hrdps",
)


def cpu_supported(
    cpuinfo: Path = Path("/proc/cpuinfo"), machine: str | None = None
) -> tuple[bool | None, str]:
    """Whether this CPU can run the server: AVX2 on x86, or ARM64. None when unknown."""
    arch = (machine or platform.machine()).lower()
    if arch in ("aarch64", "arm64"):
        return True, "ARM64"
    try:
        text = cpuinfo.read_text()
    except OSError:
        return None, f"unknown ({arch}; no {cpuinfo})"
    flags = set(re.findall(r"\b[a-z0-9_]+\b", " ".join(re.findall(r"^flags\s*:(.*)$", text, re.M))))
    if "avx2" in flags:
        return True, "AVX2 present"
    return False, "no AVX2: the server would stop with 'Illegal instruction'"


def _utc(ts: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ts), UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def model_runs(fetcher: Fetcher) -> list[str]:
    """Each model folder's last run and when it became available."""
    lines = []
    now = datetime.now(UTC)
    for model in MODEL_FOLDERS:
        url = f"{DATA_URL}/{model}/static/meta.json"
        try:
            meta = fetcher.get_json(url, source="open-meteo-data")
        except FetchError as e:
            lines.append(f"  {model:16s} error: {e}")
            continue
        init = _utc(meta.get("last_run_initialisation_time"))
        avail = _utc(meta.get("last_run_availability_time"))
        run = f"{init:%Y-%m-%d %H:%M} UTC" if init else "?"
        when = (
            f"available {avail:%H:%M} UTC ({(now - avail).total_seconds() / 60:.0f} min ago)"
            if avail
            else "availability unknown"
        )
        lines.append(f"  {model:16s} run {run}, {when}")
    return lines


def local_probe(fetcher: Fetcher, url: str) -> tuple[float, str | None]:
    """Seconds for one small request to the server, and the error if it failed."""
    t0 = time.monotonic()
    try:
        fetcher.get_json(
            f"{url}/v1/forecast",
            {
                "latitude": "46.93",
                "longitude": "-121.5",
                "models": "ecmwf_ifs025",
                "hourly": "temperature_2m",
                "forecast_days": "1",
            },
            source=SOURCE + LOCAL_SUFFIX,
            allow_fallback=False,
        )
    except FetchError as e:
        return time.monotonic() - t0, str(e)
    return time.monotonic() - t0, None


def openmeteo_status(
    url: str,
    fallback: bool,
    budget: int,
    usage: Any,
    fetcher: Fetcher,
    *,
    cpu: tuple[bool | None, str] | None = None,
    ensembles: tuple[bool, list[str]] | None = None,
) -> tuple[bool, list[str]]:
    """`snowwatch openmeteo status`: (all OK, lines to print). `usage` is today's ledger
    (`repo.usage_today`); `ensembles` is `ensembles.status_lines` (downloaded ensembles
    and free disk)."""
    cpu_ok, cpu_text = cpu or cpu_supported()
    lines = [f"{'OPEN_METEO_URL':16s} {url or '(empty: every request uses the public API)'}"]
    lines.append(f"{'CPU':16s} {cpu_text}")
    ok = bool(url) and cpu_ok is not False
    if url:
        secs, err = local_probe(fetcher, url)
        if err:
            ok = False
            lines.append(f"{'server':16s} FAILED after {secs:.1f} s: {err}")
        else:
            lines.append(f"{'server':16s} OK, {secs:.2f} s for one small request")
        lines.append(f"{'fallback':16s} {'on' if fallback else 'off'} (OPEN_METEO_FALLBACK)")
    each = f" ({usage.local_latency_s:.2f} s each)" if usage.local_latency_s is not None else ""
    lines.append(
        f"{'today (UTC)':16s} {usage.local_requests} self-hosted requests{each}, "
        f"{usage.fallbacks} fallbacks, {usage.public_weight:.0f} of {budget} public calls"
    )
    if ensembles is not None:
        ens_ok, ens_lines = ensembles
        ok = ok and ens_ok
        lines += ens_lines
    lines.append("model runs in the public data:")
    lines += model_runs(fetcher)
    lines.append("OK" if ok else "NOT OK")
    return ok, lines


def _points(data: Any) -> list[dict[str, Any]]:
    """An Open-Meteo answer as one dict per point (several coordinates give a list)."""
    return [d for d in (data if isinstance(data, list) else [data]) if isinstance(d, dict)]


def null_shares(data: Any) -> dict[tuple[int, str], float]:
    """The share of empty values (%) for every hourly column at every point."""
    out = {}
    for i, point in enumerate(_points(data)):
        for col, values in (point.get("hourly") or {}).items():
            if col == "time" or not isinstance(values, list) or not values:
                continue
            out[(i, col)] = 100 * sum(v is None for v in values) / len(values)
    return out


def compare_nulls(local: Any, public: Any) -> tuple[int, int, list[str], list[str]]:
    """(local columns, public columns, columns missing locally, columns whose share of
    empty values differs by more than NULL_SHARE_POINTS, as text)."""
    a, b = null_shares(local), null_shares(public)
    cols_a = {c for _, c in a}
    cols_b = {c for _, c in b}
    missing = sorted(cols_b - cols_a)
    differs = []
    for key in sorted(a.keys() & b.keys()):
        if abs(a[key] - b[key]) > NULL_SHARE_POINTS:
            point, col = key
            where = f" (point {point + 1})" if len(_points(local)) > 1 else ""
            differs.append(f"`{col}`{where} {a[key]:.0f}% vs {b[key]:.0f}%")
    return len(cols_a), len(cols_b), missing, differs


def _fixture(fixtures: Path | None, loc_id: str, name: str) -> Any | None:
    if fixtures is None:
        return None
    path = fixtures / loc_id / f"{name}.json.gz"
    if not path.exists():
        return None
    from snowwatch.capture import load_fixture

    return load_fixture(path)


def comparison_section(
    local: Fetcher,
    public: Fetcher,
    locs: list[Location],
    cfg: ForecastConfig,
    fixtures: Path | None,
) -> list[str]:
    lines = [
        "| Location | Request | Columns (local / public) | Missing locally | "
        f"Empty share differs by > {NULL_SHARE_POINTS:g} points | Compared with |",
        "|---|---|---|---|---|---|",
    ]
    public_ok = True
    for loc in locs:
        for req in location_requests(loc, cfg, ensembles=False):
            try:
                mine = fetch(local, req)
            except FetchError as e:
                lines.append(f"| {loc.name} | `{req.name}` | local error: {e} | | | |")
                continue
            theirs, against = None, "public API"
            if public_ok:
                try:
                    theirs = fetch(public, req)
                except FetchError:
                    public_ok = False  # usually 429 from a shared address: use fixtures
            if theirs is None:
                theirs, against = _fixture(fixtures, loc.id, req.name), "saved fixture"
            if theirs is None:
                n = len({c for _, c in null_shares(mine)})
                lines.append(f"| {loc.name} | `{req.name}` | {n} / - | | | nothing to compare |")
                continue
            na, nb, missing, differs = compare_nulls(mine, theirs)
            more = f" and {len(differs) - 8} more" if len(differs) > 8 else ""
            lines.append(
                f"| {loc.name} | `{req.name}` | {na} / {nb} | "
                f"{', '.join(f'`{m}`' for m in missing) or 'none'} | "
                f"{'; '.join(differs[:8]) + more or 'none'} | {against} |"
            )
    return [*lines, ""]


def ensemble_comparison_section(
    local: Fetcher,
    public: Fetcher,
    locs: list[Location],
    cfg: ForecastConfig,
    fixtures: Path | None,
) -> list[str]:
    from snowwatch import ensembles
    from snowwatch.sources.openmeteo import ensemble_request

    now = datetime.now(UTC)
    lines = [
        "| Location | System | Members (server / public) | Reach, h (server / public) | "
        "16-day totals differ by, cm (mean / max) | Compared with |",
        "|---|---|---|---|---|---|",
    ]
    public_ok = True
    for loc in locs:
        for system in cfg.ensembles:
            req = ensemble_request(loc, system)
            try:
                mine = local.shadow_ensemble(req.url, req.params, source=req.source)
            except FetchError as e:
                lines.append(f"| {loc.name} | `{system}` | server error: {e} | | | |")
                continue
            theirs, against = None, "public API"
            if public_ok:
                try:
                    theirs = fetch(public, req)
                except FetchError:
                    public_ok = False
            if theirs is None:
                theirs, against = _fixture(fixtures, loc.id, req.name), "saved fixture"
            if theirs is None:
                n = ensembles.members_with_data(mine)
                lines.append(f"| {loc.name} | `{system}` | {n} / - | | | nothing to compare |")
                continue
            c = ensembles.compare(mine, theirs, now)

            def h(x: float | None) -> str:
                return "-" if x is None else f"{x:.0f}"

            totals = f"{c.mean_diff_cm} / {c.max_diff_cm}" if against == "public API" else "-"
            reach = (
                f"{h(c.reach_local_h)} / {h(c.reach_public_h)}"
                if against == "public API"
                else f"{h(c.reach_local_h)} / -"
            )
            lines.append(
                f"| {loc.name} | `{system}` | {c.members_local} / {c.members_public} | "
                f"{reach} | {totals} | {against} |"
            )
    return [*lines, ""]


def build_local_report(
    local: Fetcher,
    public: Fetcher,
    locs: list[Location],
    cfg: ForecastConfig,
    *,
    fixtures: Path | None = None,
) -> str:
    """The `## Self-hosted Open-Meteo server` section of docs/SOURCES.md."""
    us = next((loc for loc in locs if loc.country == "US"), None)
    ca = next((loc for loc in locs if loc.country == "CA"), None)
    picked = [loc for loc in (us, ca) if loc is not None]
    lines = [
        LOCAL_HEADING,
        "",
        f"Generated by `snowwatch check-sources --local` on "
        f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} against `{local.local_url}`. "
        "Ensembles come from what the downloader put on the server (the public data it "
        "reads has no per-member snowfall).",
        "",
        "### Models and variables",
        "",
    ]
    for loc in picked:
        try:
            sec = model_section(local, loc, cfg.models_for(loc.country))
        except (FetchError, KeyError, TypeError) as e:
            lines += [f"Model check failed for {loc.name}: {e}", ""]
            continue
        lines += ["#" + sec[0], *sec[1:]]
    lines += [
        "### Empty values against the public API",
        "",
        "Each of a run's requests, sent to both; values aren't compared (a saved fixture is "
        "from another day), only which columns come back and how many of their values are "
        "empty.",
        "",
        *comparison_section(local, public, picked, cfg, fixtures),
    ]
    lines += [
        "### Ensembles against the public API",
        "",
        "The ensembles the downloader (`openmeteo-ensembles`) put on the server, each "
        "asked the same question as the public API: members with data, how far ahead they "
        "reach, and how much the members' 16-day totals differ (only against the live "
        "public API; a saved fixture is from another day).",
        "",
        *ensemble_comparison_section(local, public, picked, cfg, fixtures),
    ]
    try:
        d = fetch(local, elevation_request([(46.935, -121.475), (47.424, -121.418)]))
        lines += [f"Elevation, two points in one call: `{d}`.", ""]
    except FetchError as e:
        lines += [f"Elevation check failed: {e}", ""]
    return "\n".join(lines).rstrip() + "\n"


def merge_section(text: str, section: str, heading: str = LOCAL_HEADING) -> str:
    """`text` with its `heading` section (to the next `## ` heading) replaced by
    `section`, or `section` added at the end."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        return text.rstrip() + "\n\n" + section
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rest = "\n".join(lines[end:])
    head = "\n".join(lines[:start]).rstrip()
    out = (head + "\n\n" if head else "") + section
    return out + ("\n" + rest.rstrip() + "\n" if rest else "")


def keep_section(old: str, new: str, heading: str = LOCAL_HEADING) -> str:
    """A fresh full report (`new`) that keeps `old`'s `heading` section, if it has one."""
    lines = old.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        return new
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return merge_section(new, "\n".join(lines[start:end]).rstrip() + "\n", heading)


# --- Self-hosted ensembles against public ones, whole snapshots (check-ensembles) -----

ENSEMBLE_FLAG_CM = 1.0  # flag an ensemble figure that moves by more than this


def _walk(a: Any, b: Any, path: str, out: list[tuple[str, Any, Any, float | None]]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            _walk(a.get(k), b.get(k), f"{path}.{k}" if path else str(k), out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, f"{len(a)} items", f"{len(b)} items", None))
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            _walk(x, y, f"{path}[{i}]", out)
    elif (
        isinstance(a, int | float)
        and isinstance(b, int | float)
        and not isinstance(a, bool)
        and not isinstance(b, bool)
    ):
        if abs(a - b) > 1e-9:
            out.append((path, a, b, abs(a - b)))
    elif a != b:
        out.append((path, a, b, None))


def snapshot_differences(a: Any, b: Any) -> list[tuple[str, int, float | None, str]]:
    """Every field that differs between two snapshots (as JSON), grouped with list
    positions folded (`windows[].ens.p90`): (field, how many values differ, the largest
    change, an example)."""
    raw: list[tuple[str, Any, Any, float | None]] = []
    _walk(a, b, "", raw)
    grouped: dict[str, tuple[int, float | None, str]] = {}
    for path, x, y, delta in raw:
        field = re.sub(r"\[\d+\]", "[]", path)
        n, worst, example = grouped.get(field, (0, None, ""))
        if delta is not None and (worst is None or delta > worst):
            worst, example = delta, f"{path}: {x} vs {y}"
        elif not example:
            example = f"{path}: {x} vs {y}"
        grouped[field] = (n + 1, worst, example)
    return [(f, n, w, e) for f, (n, w, e) in sorted(grouped.items())]


def _over(field: str, worst: float | None) -> bool:
    """Whether a difference matters: a member count (`n`) that changes at all, a list
    that changes length, or any figure moving by more than ENSEMBLE_FLAG_CM."""
    if worst is None:
        return True
    if field.endswith(".n"):
        return worst > 0
    return worst > ENSEMBLE_FLAG_CM


def check_ensembles(
    fetcher: Fetcher, locs: list[Location], cfg: ForecastConfig, now: datetime | None = None
) -> tuple[bool, str]:
    """`snowwatch check-ensembles`: for each location, one run's forecasts, then its
    snapshot built twice, with the server's ensembles and with the public API's, and
    every field that differs. `fetcher` sends forecasts where the settings say, and
    ensembles to the public API (OPEN_METEO_ENSEMBLES is ignored here)."""
    from snowwatch import ensembles
    from snowwatch.analysis.build import build_snapshot
    from snowwatch.inputs import inputs_from_responses
    from snowwatch.sources.openmeteo import ensemble_request

    now = now or datetime.now(UTC)
    ok = True
    runs = []
    for system in cfg.ensembles:
        mine = fetcher.ensemble_run(system) if fetcher.ensemble_run else None
        theirs = ensembles.public_run(
            lambda url: fetcher.get_json(url, source="open-meteo-data"), system
        )
        same = "" if mine and mine == theirs else " (**different runs**: differences expected)"
        runs.append(
            f"{ensembles.label(system)}: server {mine:%d %b %H}z, public {theirs:%d %b %H}z{same}"
            if mine and theirs
            else f"{ensembles.label(system)}: runs unknown"
        )
    lines = [
        "## Self-hosted ensembles against the public API",
        "",
        f"Generated by `snowwatch check-ensembles` on {now:%Y-%m-%d %H:%M UTC}. Each "
        "location's snapshot is built twice from the same forecasts, once with the "
        "server's ensembles and once with the public API's; every field that differs is "
        f"listed. Flagged: more than {ENSEMBLE_FLAG_CM:g} cm, or any change in a member "
        "count or a list's length. Only runs that match are a fair test.",
        "",
        "Runs: " + "; ".join(runs) + ".",
        "",
    ]
    for loc in locs:
        responses: dict[str, Any] = {}
        problems = []
        for req in location_requests(loc, cfg, ensembles=False):
            try:
                responses[req.name] = fetch(fetcher, req)
            except FetchError as e:
                problems.append(f"{req.name}: {e}")
        local: dict[str, Any] = {}
        public: dict[str, Any] = {}
        for system in cfg.ensembles:
            req = ensemble_request(loc, system)
            try:
                local[req.name] = fetcher.shadow_ensemble(req.url, req.params, source=req.source)
                public[req.name] = fetch(fetcher, req)
            except FetchError as e:
                problems.append(f"{req.name}: {e}")
                local.pop(req.name, None)
        lines += [f"### {loc.name}", ""]
        if "blend" not in responses or "multi" not in responses or not local:
            ok = False
            lines += [f"Not checked: {'; '.join(problems) or 'no ensembles'}", ""]
            continue
        try:
            a, _ = build_snapshot(loc, inputs_from_responses(loc, responses | local, cfg), cfg, now)
            b, _ = build_snapshot(
                loc, inputs_from_responses(loc, responses | public, cfg), cfg, now
            )
        except Exception as e:  # report it and go on with the others
            ok = False
            lines += [f"Not checked: {type(e).__name__}: {e}", ""]
            continue
        diffs = snapshot_differences(a.model_dump(mode="json"), b.model_dump(mode="json"))
        flagged = [d for d in diffs if _over(d[0], d[2])]
        ok = ok and not flagged
        systems = ", ".join(k.removeprefix("ens_") for k in local)
        lines.append(
            f"Compared: {systems}. {len(diffs)} fields differ, {len(flagged)} flagged."
            + (f" Skipped: {'; '.join(problems)}." if problems else "")
        )
        lines.append("")
        if diffs:
            lines += [
                "| Field | Values that differ | Largest change | Example (server vs public) |",
                "|---|---|---|---|",
            ]
            for field, n, worst, example in diffs:
                mark = " **(flagged)**" if _over(field, worst) else ""
                change = "-" if worst is None else f"{worst:.2f}"
                lines.append(f"| `{field}`{mark} | {n} | {change} | {example[:120]} |")
            lines.append("")
    lines.append("OK" if ok else "NOT OK: see the flagged fields")
    return ok, "\n".join(lines) + "\n"
