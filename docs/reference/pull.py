#!/usr/bin/env python3
"""Snow Watch data pull (v2).

For each location fetches, from Open-Meteo: a high-resolution blend at base, mid
and summit elevations (hourly, 11 days); four individual models at mid (hourly
snowfall, 16 days); and the GFS + ECMWF ensembles at mid (82 members). Also NWS
active alerts and SNOTEL for the Washington sites, and the latest NWS forecast
discussions (text for the written summaries).

Writes out/<id>.json per location, out/meta.json and out/afd.txt.
Usage: python3 pull.py [outdir] [location ids...]
"""
import json, sys, time, datetime as dt, urllib.request, urllib.parse, urllib.error
from pathlib import Path

UA = "snowdash/2.0 (personal snow dashboard)"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
OUT.mkdir(parents=True, exist_ok=True)

NWAC = "https://nwac.us/avalanche-forecast/#/"
LOCATIONS = [
    dict(id="crystal", name="Crystal Mountain", region="WA Cascades", lat=46.935, lon=-121.475, country="US",
         elev=[("base", "Base", 1341), ("mid", "Mid-mountain", 1800), ("summit", "Summit", 2095)],
         snotel="642:WA:SNTL", afd=["SEW"],
         links={"Radar (Seattle)": "https://radar.weather.gov/station/katx/standard",
                "NWS forecast": "https://forecast.weather.gov/MapClick.php?lat=46.935&lon=-121.475",
                "Avalanche (NWAC)": NWAC + "west-slopes-central",
                "Mountain passes (WSDOT)": "https://wsdot.com/travel/real-time/mountainpasses/"}),
    dict(id="snoqualmie", name="Snoqualmie Pass", region="WA Cascades", lat=47.424, lon=-121.418, country="US",
         elev=[("base", "Base", 914), ("mid", "Upper lifts", 1150), ("summit", "Alpental top", 1652)],
         snotel="672:WA:SNTL", afd=["SEW"],
         links={"Radar (Seattle)": "https://radar.weather.gov/station/katx/standard",
                "NWS forecast": "https://forecast.weather.gov/MapClick.php?lat=47.424&lon=-121.418",
                "Avalanche (NWAC)": NWAC + "snoqualmie-pass",
                "Pass report (WSDOT)": "https://wsdot.com/travel/real-time/mountainpasses/snoqualmie"}),
    dict(id="rainy", name="Heather–Maple / Rainy Pass", region="North Cascades", lat=48.518, lon=-120.735, country="US",
         elev=[("base", "Rainy Pass trailhead", 1480), ("mid", "Heather Pass", 1890), ("summit", "Maple Pass", 2124)],
         snotel="711:WA:SNTL", afd=["OTX", "SEW"],
         links={"Radar (Seattle)": "https://radar.weather.gov/station/katx/standard",
                "NWS forecast": "https://forecast.weather.gov/MapClick.php?lat=48.518&lon=-120.735",
                "Avalanche (NWAC)": NWAC + "east-slopes-north",
                "SR 20 status (WSDOT)": "https://wsdot.com/travel/real-time/mountainpasses/north-cascades"}),
    dict(id="whistler", name="Whistler", region="BC Coast Mountains", lat=50.06, lon=-122.95, country="CA",
         elev=[("base", "Village", 675), ("mid", "Roundhouse", 1850), ("summit", "Peak", 2182)],
         snotel=None, afd=[],
         links={"Radar (ECCC)": "https://weather.gc.ca/radar/index_e.html?id=CASSS",
                "Mountain forecast (ECCC)": "https://weather.gc.ca/mountain_forecast/",
                "Avalanche Canada": "https://avalanche.ca/map",
                "Hwy 99 (DriveBC)": "https://www.drivebc.ca/"}),
    dict(id="revelstoke", name="Revelstoke", region="BC Interior (Selkirks)", lat=51.00, lon=-118.16, country="CA",
         elev=[("base", "Base", 512), ("mid", "Mid-mountain", 1500), ("summit", "Summit", 2225)],
         snotel=None, afd=[],
         links={"Radar (ECCC)": "https://weather.gc.ca/radar/index_e.html?id=CASSR",
                "Mountain forecast (ECCC)": "https://weather.gc.ca/mountain_forecast/",
                "Avalanche Canada": "https://avalanche.ca/map",
                "Hwy 1 (DriveBC)": "https://www.drivebc.ca/"}),
    dict(id="sunshine", name="Banff Sunshine", region="AB Rockies", lat=51.08, lon=-115.77, country="CA",
         elev=[("base", "Parking lot", 1658), ("mid", "Village", 2160), ("summit", "Lookout Mtn", 2730)],
         snotel=None, afd=[],
         links={"Radar (ECCC)": "https://weather.gc.ca/radar/index_e.html?id=CASSM",
                "Mountain forecast (ECCC)": "https://weather.gc.ca/mountain_forecast/",
                "Avalanche Canada": "https://avalanche.ca/map",
                "Hwy 1 (511 Alberta)": "https://511.alberta.ca/"}),
]

MODELS = {"gfs": "gfs_seamless", "ecmwf": "ecmwf_ifs025", "gem": "gem_seamless", "icon": "icon_seamless"}
ENS_MODELS = ["gfs_seamless", "ecmwf_ifs025"]
CM2IN, MM2IN, M2FT, KMH2MPH = 1 / 2.54, 1 / 25.4, 3.28084, 0.621371
N_PERIODS = 20       # 10 days of day/night periods
HOURLY_KEEP = 240    # 10 days of hourly rows
SNOW_LEVEL_OFFSET_FT = 1000  # snow level ~ 1,000 ft below the freezing level


def get(url, params=None, tries=6, timeout=40):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, application/geo+json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(65 if e.code == 429 else 2 + 3 * i)  # Open-Meteo free tier: per-minute limit
        except Exception as e:
            last = e
            time.sleep(2 + 3 * i)
    raise RuntimeError(f"GET failed after {tries} tries: {url[:110]} ({last})")


def r1(x, nd=1):
    return None if x is None else round(x, nd)


def c2f(c):
    return None if c is None else c * 9 / 5 + 32


def ft50(m):
    return None if m is None else int(round(m * M2FT / 50) * 50)


def pct(vals, q):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * q
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def median(vals):
    return pct(vals, 0.5)


def ptype(snow_in, rain_in):
    if (snow_in or 0) < 0.05 and (rain_in or 0) < 0.01:
        return "none"
    if (rain_in or 0) < 0.01:
        return "snow"
    if (snow_in or 0) < 0.05:
        return "rain"
    return "mix"


def quality(temp_f):
    """Rough snow-to-liquid ratio and label from air temperature at the location."""
    if temp_f is None:
        return None, None
    if temp_f >= 31:
        return 8, "Heavy & wet"
    if temp_f >= 26:
        return 11, "Average"
    if temp_f >= 19:
        return 14, "Light"
    return 17, "Dry & fluffy"


def period_key(t):
    """12 h periods: day 06–18, night 18–06 (night belongs to the evening's date). Local time."""
    d = dt.datetime.fromisoformat(t)
    if 6 <= d.hour < 18:
        return (d.date().isoformat(), "day")
    if d.hour >= 18:
        return (d.date().isoformat(), "night")
    return ((d.date() - dt.timedelta(days=1)).isoformat(), "night")


def period_label(key, today):
    date, kind = key
    wd = dt.date.fromisoformat(date).strftime("%a")
    if date == today:
        return "Today" if kind == "day" else "Tonight"
    if date < today:  # the early-morning hours of last night
        return "Overnight"
    return wd if kind == "day" else wd + " night"


def fetch(loc):
    mid_m = [e for e in loc["elev"] if e[0] == "mid"][0][2]
    lat, lon = loc["lat"], loc["lon"]
    hv = ("temperature_2m,snowfall,rain,showers,precipitation,precipitation_probability,freezing_level_height,"
          "wind_speed_10m,wind_gusts_10m,wind_direction_10m,cloud_cover,weather_code")
    det = get("https://api.open-meteo.com/v1/forecast", dict(
        latitude=",".join([str(lat)] * 3), longitude=",".join([str(lon)] * 3),
        elevation=",".join(str(e[2]) for e in loc["elev"]), timezone="auto", past_days=1, forecast_days=11,
        hourly=hv, current="temperature_2m,weather_code,wind_speed_10m,wind_gusts_10m,freezing_level_height"))
    multi = get("https://api.open-meteo.com/v1/forecast", dict(
        latitude=lat, longitude=lon, elevation=mid_m, timezone="auto", forecast_days=16,
        hourly="snowfall", models=",".join(MODELS.values())))
    ens = {}
    for m in ENS_MODELS:
        try:
            ens[m] = get("https://ensemble-api.open-meteo.com/v1/ensemble", dict(
                latitude=lat, longitude=lon, elevation=mid_m, timezone="auto", forecast_days=16,
                hourly="snowfall", models=m))
        except Exception as e:
            print(f"  ensemble {m} failed for {loc['id']}: {e}", file=sys.stderr)
    return det, multi, ens


def hourly_rows(block, i0, n):
    H = block["hourly"]
    rows = []
    for i in range(i0, min(i0 + n, len(H["time"]))):
        snow = (H["snowfall"][i] or 0) * CM2IN
        rain = ((H["rain"][i] or 0) + (H["showers"][i] or 0)) * MM2IN
        temp = c2f(H["temperature_2m"][i])
        fl = ft50(H["freezing_level_height"][i])
        slr, q = quality(temp) if snow >= 0.05 else (None, None)
        rows.append(dict(
            t=H["time"][i], snow=r1(snow, 2), liq=r1((H["precipitation"][i] or 0) * MM2IN, 2), rain=r1(rain, 2),
            temp=r1(temp), fl=fl, snowlvl=None if fl is None else max(0, fl - SNOW_LEVEL_OFFSET_FT),
            pop=H["precipitation_probability"][i], wind=r1((H["wind_speed_10m"][i] or 0) * KMH2MPH, 0),
            gust=r1((H["wind_gusts_10m"][i] or 0) * KMH2MPH, 0), wdir=H["wind_direction_10m"][i],
            cloud=H["cloud_cover"][i], wcode=H["weather_code"][i], ptype=ptype(snow, rain), slr=slr, quality=q))
    return rows


def build(loc):
    det, multi, ens = fetch(loc)
    bands = {e[0]: (e, blk) for e, blk in zip(loc["elev"], det)}
    mid = bands["mid"][1]
    cur = mid["current"]
    times = mid["hourly"]["time"]
    now_t = cur["time"][:13] + ":00"
    i0 = times.index(now_t) if now_t in times else 0
    today = cur["time"][:10]

    # hourly at mid, from now to the end of the run
    all_hours = [h for h in hourly_rows(mid, i0, len(times)) if h["temp"] is not None]
    hourly = all_hours[:HOURLY_KEEP]

    # per-model and ensemble hourly snowfall, keyed by local time
    MH = multi["hourly"]
    model_h = {k: {t: (v * CM2IN if v is not None else None) for t, v in zip(MH["time"], MH.get(f"snowfall_{m}") or [])}
               for k, m in MODELS.items()}
    members = []
    for e in ens.values():
        eh = e["hourly"]
        for key, vals in eh.items():
            if key.startswith("snowfall"):
                members.append({t: (v * CM2IN if v is not None else None) for t, v in zip(eh["time"], vals)})

    def model_sum(k, ts):
        vals = [model_h[k].get(t) for t in ts]
        if not ts or any(v is None for v in vals):
            return None
        return sum(vals)

    def member_sums(ts):
        out = []
        for mm in members:
            vals = [mm.get(t) for t in ts]
            if ts and all(v is not None for v in vals):
                out.append(sum(vals))
        return out

    # day/night periods from now
    order, groups = [], {}
    for h in all_hours:
        k = period_key(h["t"])
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(h)
    order = [k for k in order if len(groups[k]) >= 6 or k == order[0]]  # drop a trailing fragment
    periods = []
    for k in order[:N_PERIODS]:
        hs = groups[k]
        ts = [h["t"] for h in hs]
        hr = sum(h["snow"] or 0 for h in hs)
        mods = {mk: model_sum(mk, ts) for mk in MODELS}
        ms = member_sums(ts)
        ens_mean = sum(ms) / len(ms) if ms else None
        dets = [v for v in mods.values() if v is not None]
        if len(periods) < 4:
            dets.append(hr)  # high-res blend adds value in the first 48 h
        # consensus: median of the individual models while at least 3 are running;
        # later, when only one or two remain, the ensemble mean is more trustworthy
        if len(dets) >= 3:
            cons, basis = median(dets), "models"
        elif ens_mean is not None:
            cons, basis = ens_mean, "ensemble"
        else:
            cons, basis = median(dets + [hr]), "models"
        avail = dets
        snow_hours = [h for h in hs if (h["snow"] or 0) >= 0.05]
        tq = median([h["temp"] for h in snow_hours]) if snow_hours else None
        slr, q = quality(tq) if snow_hours else (None, None)
        rain = sum(h["rain"] or 0 for h in hs)
        periods.append(dict(
            key=f"{k[0]}-{k[1]}", date=k[0], kind=k[1], label=period_label(k, today), hours=len(hs),
            start=ts[0], cons=r1(cons), basis=basis, hr=r1(hr), **{mk: r1(v) for mk, v in mods.items()},
            nmodels=len(avail), ens_mean=r1(ens_mean), ens_p10=r1(pct(ms, .1)), ens_p50=r1(pct(ms, .5)),
            ens_p90=r1(pct(ms, .9)), cloud=round(sum(h["cloud"] or 0 for h in hs) / len(hs)),
            ens_n=len(ms), liq=r1(sum(h["liq"] or 0 for h in hs), 2), rain=r1(rain, 2),
            tmax=r1(max(h["temp"] for h in hs)), tmin=r1(min(h["temp"] for h in hs)),
            snowlvl_min=min((h["snowlvl"] for h in hs if h["snowlvl"] is not None), default=None),
            wind_max=max(h["wind"] for h in hs), gust_max=max(h["gust"] for h in hs),
            pop_max=max((h["pop"] for h in hs if h["pop"] is not None), default=None),
            ptype=ptype(hr, rain), slr=slr, quality=q))

    def window(a, b):
        ps = periods[a:b]
        if not ps:
            return dict(cons=None, hr=None, p10=None, p50=None, p90=None, prob1=None, prob6=None, prob12=None)
        ts = [h["t"] for k in order[a:b] for h in groups[k]]
        ms = member_sums(ts)
        n = len(ms) or 1
        prob = lambda x: round(100 * sum(v >= x for v in ms) / n) if ms else None
        return dict(cons=r1(sum(p["cons"] or 0 for p in ps)), hr=r1(sum(p["hr"] or 0 for p in ps)),
                    p10=r1(pct(ms, .1)), p50=r1(pct(ms, .5)), p90=r1(pct(ms, .9)),
                    prob1=prob(1), prob6=prob(6), prob12=prob(12))

    w5, w10 = window(0, 10), window(10, 20)

    # elevation bands (high-res blend at each elevation)
    elevs = []
    for band, (e, blk) in bands.items():
        H = blk["hourly"]
        bt = H["time"]
        j0 = bt.index(now_t) if now_t in bt else 0
        sn = [(v or 0) * CM2IN for v in H["snowfall"]]
        temps = [c2f(t) for t in H["temperature_2m"][j0:j0 + 24] if t is not None]
        elevs.append(dict(band=band, label=e[1], elev_ft=int(round(e[2] * M2FT / 10) * 10),
                          last24=r1(sum(sn[max(0, j0 - 24):j0])), next24=r1(sum(sn[j0:j0 + 24])),
                          next5=r1(sum(sn[j0:j0 + 120])), d6_10=r1(sum(sn[j0 + 120:j0 + 240])),
                          temp_now=r1(c2f(H["temperature_2m"][j0])),
                          tmin24=r1(min(temps)) if temps else None, tmax24=r1(max(temps)) if temps else None))

    # 15-day daily model comparison at mid
    dates = sorted({t[:10] for t in MH["time"] if t[:10] >= today})[:15]
    daily, cum, running = [], {k: 0.0 for k in MODELS}, None
    for d in dates:
        ts = [t for t in MH["time"] if t.startswith(d)]
        row = dict(date=d)
        for k in MODELS:
            v = model_sum(k, ts)
            row[k] = r1(v)
            cum[k] = None if (v is None or cum[k] is None) else cum[k] + v
            row[k + "_cum"] = r1(cum[k])
        per = []
        for mm in members:
            vals = [mm.get(t) for t in ts]
            per.append(sum(vals) if ts and all(v is not None for v in vals) else None)
        running = per if running is None else [None if (a is None or b is None) else a + b for a, b in zip(running, per)]
        valid = [v for v in running if v is not None]
        ok = len(valid) >= 10
        dv = [v for v in per if v is not None]
        row.update(ens_p10=r1(pct(dv, .1)) if ok else None, ens_p50=r1(pct(dv, .5)) if ok else None,
                   ens_p90=r1(pct(dv, .9)) if ok else None,
                   ens_cum_p10=r1(pct(valid, .1)) if ok else None, ens_cum_p50=r1(pct(valid, .5)) if ok else None,
                   ens_cum_p90=r1(pct(valid, .9)) if ok else None)
        daily.append(row)
    sl_by_day = {}
    for h in all_hours:
        if h["snowlvl"] is not None:
            sl_by_day.setdefault(h["t"][:10], []).append(h["snowlvl"])
    for row in daily:
        row["snowlvl_min"] = min(sl_by_day[row["date"]]) if row["date"] in sl_by_day else None

    mid_e = [e for e in elevs if e["band"] == "mid"][0]
    now = dict(time=cur["time"], tz=mid.get("timezone"), temp_f=r1(c2f(cur["temperature_2m"])),
               wind_mph=r1(cur["wind_speed_10m"] * KMH2MPH, 0), gust_mph=r1(cur["wind_gusts_10m"] * KMH2MPH, 0),
               weather_code=cur["weather_code"], fl_ft=ft50(cur.get("freezing_level_height")),
               last24=mid_e["last24"])
    now["snowlvl_ft"] = None if now["fl_ft"] is None else max(0, now["fl_ft"] - SNOW_LEVEL_OFFSET_FT)
    return dict(id=loc["id"], name=loc["name"], region=loc["region"], country=loc["country"], lat=loc["lat"],
                lon=loc["lon"], elev_ft=mid_e["elev_ft"], mid_label=mid_e["label"], links=loc["links"], now=now,
                next5=w5, d6_10=w10, ens_members=len(members), hourly=hourly, periods=periods, elevs=elevs,
                daily=daily)


def pull_snotel(triplet):
    base = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
    meta = get(f"{base}/stations", dict(stationTriplets=triplet, returnForecastPointMetadata="false"))[0]
    end = dt.date.today()
    daily = get(f"{base}/data", dict(stationTriplets=triplet, elements="SNWD,WTEQ", duration="DAILY",
                                     beginDate=(end - dt.timedelta(days=45)).isoformat(), endDate=end.isoformat()))
    hourly = get(f"{base}/data", dict(stationTriplets=triplet, elements="SNWD", duration="HOURLY",
                                      beginDate=(end - dt.timedelta(days=4)).isoformat() + " 00:00",
                                      endDate=end.isoformat() + " 23:59"))

    def series(blob, el):
        for st in blob:
            for d in st.get("data", []):
                if d["stationElement"]["elementCode"] == el:
                    return [(v["date"], v.get("value")) for v in d.get("values", [])]
        return []

    sd, sw = dict(series(daily, "SNWD")), dict(series(daily, "WTEQ"))
    rows = [[d[:10], sd.get(d), sw.get(d)] for d in sorted(set(sd) | set(sw))]
    hv = [(t, v) for t, v in series(hourly, "SNWD") if v is not None]

    def change(hours):
        if not hv:
            return None
        tl = dt.datetime.fromisoformat(hv[-1][0])
        prior = [v for t, v in hv if dt.datetime.fromisoformat(t) <= tl - dt.timedelta(hours=hours)]
        return None if not prior else r1(hv[-1][1] - prior[-1])

    return dict(name=meta["name"], elev_ft=int(meta["elevation"]), obs_time=hv[-1][0] if hv else None,
                depth_in=hv[-1][1] if hv else next((r[1] for r in reversed(rows) if r[1] is not None), None),
                swe_in=next((r[2] for r in reversed(rows) if r[2] is not None), None),
                change24=change(24), change72=change(72), daily=rows[-30:])


def pull_alerts(lat, lon):
    a = get("https://api.weather.gov/alerts/active", dict(point=f"{lat},{lon}"))
    return [dict(event=p.get("event"), headline=p.get("headline"), severity=p.get("severity"),
                 onset=p.get("onset"), ends=p.get("ends") or p.get("expires"))
            for p in (f["properties"] for f in a.get("features", []))]


def pull_afd(office):
    lst = get(f"https://api.weather.gov/products/types/AFD/locations/{office}")
    latest = lst["@graph"][0]
    return latest["issuanceTime"], get(latest["@id"])["productText"]


def main():
    started = dt.datetime.now(dt.timezone.utc)
    errors, afds = [], {}
    only = set(sys.argv[2:])
    locs = [l for l in LOCATIONS if not only or l["id"] in only]
    for o in sorted({o for l in locs for o in l["afd"]}):
        try:
            afds[o] = pull_afd(o)
        except Exception as e:
            errors.append(f"AFD {o}: {e}")
    for n, loc in enumerate(locs):
        if n:
            time.sleep(20)  # spread requests under Open-Meteo's per-minute limit
        print(f"pulling {loc['id']}…", file=sys.stderr, flush=True)
        try:
            doc = build(loc)
        except Exception as e:
            errors.append(f"forecast {loc['id']}: {e}")
            continue
        doc["snotel"], doc["alerts"] = None, []
        if loc["snotel"]:
            try:
                doc["snotel"] = pull_snotel(loc["snotel"])
            except Exception as e:
                errors.append(f"SNOTEL {loc['id']}: {e}")
        if loc["country"] == "US":
            try:
                doc["alerts"] = pull_alerts(loc["lat"], loc["lon"])
            except Exception as e:
                errors.append(f"alerts {loc['id']}: {e}")
        (OUT / f"{loc['id']}.json").write_text(json.dumps(doc, separators=(",", ":")))
    if afds:
        with open(OUT / "afd.txt", "w") as f:
            for o, (t, txt) in afds.items():
                f.write(f"===== NWS {o} AFD issued {t} =====\n{txt}\n\n")
    meta = dict(updated=started.isoformat(timespec="seconds"), order=[l["id"] for l in LOCATIONS],
                errors=errors, afd_issued={o: t for o, (t, _) in afds.items()})
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
