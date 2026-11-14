"""A plain-text view of a snapshot (`snowwatch show ID`), in inches, °F and feet."""

from __future__ import annotations

from snowwatch.doc import EnsStats, Snapshot

SHORT = {
    "gfs_seamless": "GFS",
    "ecmwf_ifs025": "ECMWF",
    "gem_seamless": "GEM",
    "icon_seamless": "ICON",
    "ncep_hrrr_conus": "HRRR",
    "ncep_nbm_conus": "NBM",
    "gem_hrdps_continental": "HRDPS",
}


def _in(cm: float | None) -> str:
    return "–" if cm is None else f"{cm / 2.54:.1f}"


def _f(c: float | None) -> str:
    return "–" if c is None else f"{c * 9 / 5 + 32:.0f}"


def _ft(m: float | None) -> str:
    return "–" if m is None else f"{round(m * 3.28084 / 100) * 100:,.0f}"


def _mph(kmh: float | None) -> str:
    return "–" if kmh is None else f"{kmh * 0.621371:.0f}"


def _range(e: EnsStats | None) -> str:
    if e is None:
        return "–"
    mark = "~" if e.estimated else ""
    return f"{mark}{_in(e.p10)}–{_in(e.p90)}"


ENSEMBLES = {"gfs_seamless": "GEFS", "ecmwf_ifs025": "ECMWF ENS", "gem_global": "GEPS"}


def _ensembles(snap: Snapshot) -> str:
    return ", ".join(f"{ENSEMBLES.get(s, s)} {n}" for s, n in snap.ensembles.items()) or "none"


def render(snap: Snapshot, band: str = "mid") -> str:
    b = next(x for x in snap.bands if x.band == band)
    models = [m for m in snap.models if any(m in p.models for p in b.periods)]
    lines = [
        f"{snap.location.name} · {b.label} {_ft(b.elev_m)} ft ({b.elev_m:.0f} m) · "
        f"run {snap.run_id} · {snap.now}",
        f"Ensembles: {_ensembles(snap)} · depth: {snap.depth_method}"
        + (f" · ensemble mean from {snap.basis_switch}" if snap.basis_switch else ""),
        "",
    ]
    for name, title in (("next5", "Next 5 days"), ("d6_10", "Days 6–10")):
        w = b.windows[name]
        lines.append(
            f"{title}: {_in(w.snow_cm)} in (model snowfall at 7:1 {_in(w.snow_cm_raw)} in), "
            f"ensemble 10–90%: {_range(w.ens)} in"
        )
    s = b.stats
    lines += [
        f"Now {_f(s.temp_now_c)}°F, next 24 h {_f(s.tmin24_c)}–{_f(s.tmax24_c)}°F · "
        f"last 24 h {_in(s.last24_cm)} in · next 24 h {_in(s.next24_cm)} in",
        "",
    ]
    head = f"{'Period':14s} {'Snow':>5s} {'7:1':>5s} {'Type':5s} {'Basis':8s}"
    head += "".join(f" {SHORT.get(m, m)[:6]:>6s}" for m in models)
    head += f" {'Ens 10-90':>10s} {'Hi/Lo°F':>8s} {'SnowLvl':>8s} {'Gust':>5s}"
    lines += [head, "-" * len(head)]
    for p in b.periods:
        row = (
            f"{p.label:14s} {_in(p.snow_cm):>5s} {_in(p.snow_cm_raw):>5s} {p.ptype:5s} "
            f"{(p.basis or '–'):8s}"
        )
        row += "".join(f" {_in(p.models.get(m)) if m in p.models else '':>6s}" for m in models)
        row += (
            f" {_range(p.ens):>10s} {_f(p.tmax_c) + '/' + _f(p.tmin_c):>8s}"
            f" {_ft(p.snow_level_min_m):>8s} {_mph(p.gust_max_kmh):>5s}"
        )
        lines.append(row)
    if snap.snotel:
        o = snap.snotel
        lines += [
            "",
            f"SNOTEL {o.name or o.triplet}: depth {_in(o.depth_cm)} in, "
            f"SWE {_in((o.swe_mm or 0) / 10)} in, 24 h change {_in(o.change24_cm)} in "
            f"({o.obs_time})",
        ]
    if snap.alerts:
        lines += ["", *[f"NWS: {a.event} – {a.headline}" for a in snap.alerts]]
    if snap.warnings:
        lines += ["", *[f"warning: {w}" for w in snap.warnings]]
    return "\n".join(lines) + "\n"
