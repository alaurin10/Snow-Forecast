#!/usr/bin/env python3
"""Turn pull.py output (out/<id>.json) into the dashboard's row datasets.

Usage: python3 build_datasets.py out datasets
Writes datasets/sites, periods, hourly, elevations, daily, snotel (.json); NWS alerts are columns on sites
"""
import json, sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)
meta = json.loads((src / "meta.json").read_text())
T = {k: [] for k in ["sites", "periods", "hourly", "elevations", "daily", "snotel"]}


def rng(a, b):
    return None if a is None or b is None else f"{a:g}–{b:g}"


for order, sid in enumerate(meta["order"]):
    f = src / f"{sid}.json"
    if not f.exists():
        continue
    d = json.loads(f.read_text())
    n, w5, w10, s = d["now"], d["next5"], d["d6_10"], d.get("snotel") or {}
    alerts = d.get("alerts") or []
    T["sites"].append(dict(
        site=sid, order=order, name=d["name"], region=d["region"], country=d["country"],
        elev_ft=d["elev_ft"], mid_label=d["mid_label"], tz=n["tz"], obs_time=n["time"],
        temp_f=n["temp_f"], wind_mph=n["wind_mph"], gust_mph=n["gust_mph"], snowlvl_ft=n["snowlvl_ft"],
        last24=n["last24"], next5=w5["cons"], d6_10=w10["cons"],
        next5_p10=w5["p10"], next5_p50=w5["p50"], next5_p90=w5["p90"], next5_range=rng(w5["p10"], w5["p90"]),
        d6_10_p10=w10["p10"], d6_10_p50=w10["p50"], d6_10_p90=w10["p90"], d6_10_range=rng(w10["p10"], w10["p90"]),
        prob1=w5["prob1"], prob6=w5["prob6"], prob12=w5["prob12"],
        prob1_d6_10=w10["prob1"], prob6_d6_10=w10["prob6"], prob12_d6_10=w10["prob12"],
        ens_members=d["ens_members"], alert_count=len(alerts), alert_event=alerts[0]["event"] if alerts else "",
        alert_text=" · ".join(a.get("headline") or a.get("event") or "" for a in alerts),
        snotel_name=s.get("name"), snotel_elev_ft=s.get("elev_ft"), snotel_time=s.get("obs_time"),
        depth_in=s.get("depth_in"), swe_in=s.get("swe_in"), depth_change24=s.get("change24"),
        links=json.dumps(d["links"])))
    for i, p in enumerate(d["periods"]):
        T["periods"].append(dict(site=sid, idx=i, **{k: p.get(k) for k in [
            "key", "label", "kind", "date", "start", "hours", "cons", "basis", "hr", "gfs", "ecmwf", "gem", "icon",
            "ens_mean", "ens_p10", "ens_p50", "ens_p90", "liq", "rain", "tmin", "tmax", "snowlvl_min",
            "wind_max", "gust_max", "pop_max", "cloud", "ptype", "quality"]}))
    for h in d["hourly"]:
        T["hourly"].append(dict(site=sid, **{k: h.get(k) for k in [
            "t", "snow", "liq", "rain", "temp", "snowlvl", "pop", "wind", "gust", "wdir", "cloud", "ptype", "quality"]}))
    for e in d["elevs"]:
        T["elevations"].append(dict(site=sid, **e))
    for r in d["daily"]:
        T["daily"].append(dict(site=sid, **r))
    for date, depth, swe in s.get("daily", []):
        T["snotel"].append(dict(site=sid, date=date, depth=depth, swe=swe))

for name, rows in T.items():
    (dst / f"{name}.json").write_text(json.dumps(rows, separators=(",", ":")))
    print(name, len(rows), "rows", (dst / f"{name}.json").stat().st_size, "bytes")
