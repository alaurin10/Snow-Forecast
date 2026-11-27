#!/bin/sh
# Snow Watch's ensemble downloader: the `openmeteo-ensembles` service in
# docker-compose.yml (compose profile `ensembles`), docs/OPEN-METEO-PLAN.md milestone 1b.
#
# It runs in the pinned Open-Meteo image (which has sh and curl, no Python) and uses the
# image's own downloaders to fetch every new run of three ensembles straight from their
# publishers, snowfall's inputs only:
#   GEFS       NOAA on AWS      0.25° to 240 h and 0.5° to 384 h, 00/06/12/18z
#   ECMWF ENS  ECMWF open data  to 360 h at 00/12z, 144 h at 06/18z
#   GEPS       Environment Canada, to 384 h, 00/12z
# into the volume it shares with the `openmeteo` server, which serves them at
# /v1/ensemble with no restart (it rereads its folders every few seconds).
#
# Every ENSEMBLES_CHECK_EVERY_S it looks for each system's newest complete run upstream
# and downloads it if it's newer than the last one done, one system at a time. It never
# backfills older runs.
#
# Disk: the 60 GB VM disk can't grow, so this script keeps its share bounded.
#   - Per-member data is one `rolling.om` per variable that the downloader rewrites
#     each run, keeping 3 past days: it doesn't grow from run to run.
#   - Everything else a run writes is deleted after it (see `extras`): the downloaders'
#     inputs, and ensemble-mean files whose time chunks would pile up. That leaves only
#     `snowfall_water_equivalent` per system, ~1.5 GB in all.
#   - Any other time chunk not written for ENSEMBLES_KEEP_DAYS is deleted too.
#   - Below ENSEMBLES_MIN_FREE_GB free, downloads are skipped (and say so in the status
#     file) until space is freed; the app's forecasts and database keep their room.
#   - The downloaders' own verbose logs go to one file per system in the volume,
#     replaced each run; only a line per download goes to `docker logs`.
#   - GENERATE_PREVIOUS_DAY=false (docker-compose.yml): no "previous day" copies.
#
# What it writes in the volume, under ensembles/:
#   status.json    per system: last run done, when, how long, ok or the last error;
#                  free disk; read by `snowwatch openmeteo status`
#   disk.log       one line per UTC day: free disk and the size of each part (90 days)
#   <system>.log   the last download's full output
#
# Settings (environment, all optional):
#   ENSEMBLES_SYSTEMS        which systems (default "gefs025 gefs05 ecmwf geps")
#   ENSEMBLES_CHECK_EVERY_S  seconds between checks (600)
#   ENSEMBLES_MIN_FREE_GB    skip downloads below this much free disk (5)
#   ENSEMBLES_KEEP_DAYS      delete time chunks not written for this long (3)
#   ENSEMBLES_TIMEOUT        give up a download after this long (2h; `timeout` syntax)
#   ENSEMBLES_ONCE=1         one pass, then exit (for testing)
set -u

DATA=${ENSEMBLES_DATA:-/app/data}
STATE=$DATA/ensembles
BIN=${OPENMETEO_BIN:-/app/openmeteo-api}
SYSTEMS=${ENSEMBLES_SYSTEMS:-gefs025 gefs05 ecmwf geps}
CHECK_EVERY_S=${ENSEMBLES_CHECK_EVERY_S:-600}
MIN_FREE_GB=${ENSEMBLES_MIN_FREE_GB:-5}
KEEP_DAYS=${ENSEMBLES_KEEP_DAYS:-3}
TIMEOUT=${ENSEMBLES_TIMEOUT:-2h}
RETRY_AFTER_S=1800 # after a failed download
THROTTLED_AFTER_S=3600 # after an upstream says slow down (SlowDown, 429, 503)
LOOK_BACK_H=30 # how far back to look for a complete run

GEFS_URL=${GEFS_URL:-https://noaa-gefs-pds.s3.amazonaws.com}
ECMWF_URL=${ECMWF_URL:-https://data.ecmwf.int/forecasts}
ECMWF_AWS_URL=${ECMWF_AWS_URL:-https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com}
GEPS_URL=${GEPS_URL:-https://hpfx.collab.science.gc.ca}
BUCKET_URL=${BUCKET_URL:-https://openmeteo.s3.amazonaws.com/data}

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ensembles: $*"; }

now() { echo "${ENSEMBLES_NOW:-$(date -u +%s)}"; }

iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }

# Hours between a system's runs, and the folders it writes (members, then the mean).
step_h() {
	case $1 in
	geps) echo 12 ;;
	*) echo 6 ;;
	esac
}

folders() {
	case $1 in
	gefs025) echo "ncep_gefs025 ncep_gefs025_ensemble_mean" ;;
	gefs05) echo "ncep_gefs05 ncep_gefs05_ensemble_mean" ;;
	ecmwf) echo "ecmwf_ifs025_ensemble ecmwf_ifs025_ensemble_mean" ;;
	geps) echo "cmc_gem_geps cmc_gem_geps_ensemble_mean" ;;
	esac
}

# Candidate runs (YYYYMMDDHH), newest first, over the last LOOK_BACK_H hours.
cycles() {
	step=$(($(step_h "$1") * 3600))
	t=$(($(now) / step * step))
	oldest=$(($(now) - LOOK_BACK_H * 3600))
	while [ "$t" -ge "$oldest" ]; do
		date -u -d "@$t" +%Y%m%d%H
		t=$((t - step))
	done
}

# The upstream files that exist once a run is complete: its last step.
markers() {
	sys=$1 run=$2
	d=$(echo "$run" | cut -c1-8)
	h=$(echo "$run" | cut -c9-10)
	case $sys in
	gefs025)
		echo "$GEFS_URL/gefs.$d/$h/atmos/pgrb2sp25/gep30.t${h}z.pgrb2s.0p25.f240.idx"
		;;
	gefs05)
		echo "$GEFS_URL/gefs.$d/$h/atmos/pgrb2ap5/gep30.t${h}z.pgrb2a.0p50.f384.idx"
		echo "$GEFS_URL/gefs.$d/$h/atmos/pgrb2bp5/gep30.t${h}z.pgrb2b.0p50.f384.idx"
		;;
	ecmwf)
		case $h in 00 | 12) last=360 ;; *) last=144 ;; esac
		base=$ECMWF_URL
		[ "$(ecmwf_source)" = aws ] && base=$ECMWF_AWS_URL
		echo "$base/$d/${h}z/ifs/0p25/enfo/$d${h}0000-${last}h-enfo-ef.index"
		;;
	geps)
		echo "$GEPS_URL/$d/WXO-DD/ensemble/geps/grib2/raw/$h/384/CMC_geps-raw_ASNOW_SFC_0_latlon0p5x0p5_$d${h}_P384_allmbrs.grib2"
		;;
	esac
}

# Whether a URL answers (its first byte, so it works the same on S3, Apache and ECMWF).
exists() {
	curl -sf -m 30 -r 0-0 -o /dev/null "$1"
}

newest_complete() {
	for run in $(cycles "$1"); do
		ok=1
		for url in $(markers "$1" "$run"); do
			exists "$url" || {
				ok=0
				break
			}
		done
		if [ "$ok" = 1 ]; then
			echo "$run"
			return 0
		fi
	done
	return 1
}

# Per-system state, one small file per field in $STATE/<system>/.
get() { cat "$STATE/$1/$2" 2>/dev/null || true; }
put() {
	mkdir -p "$STATE/$1"
	printf '%s\n' "$3" >"$STATE/$1/$2.tmp" && mv "$STATE/$1/$2.tmp" "$STATE/$1/$2"
}
drop() { rm -f "$STATE/$1/$2"; }

# ECMWF's open data server first; its AWS mirror after a failure there, and back.
ecmwf_source() {
	s=$(get ecmwf source)
	echo "${s:-ecmwf}"
}

free_kb() { df -Pk "$DATA" | awk 'NR == 2 { print $4 }'; }

# Disk used by one system's folders.
size_kb() {
	total=0
	for f in $(folders "$1"); do
		[ -d "$DATA/$f" ] || continue
		total=$((total + $(du -sk "$DATA/$f" | cut -f1)))
	done
	echo "$total"
}

# The image's downloader for one run of one system, as its argument list.
command_for() {
	sys=$1 run=$2
	case $sys in
	gefs025 | gefs05)
		domain=gfs025_ens
		[ "$sys" = gefs05 ] && domain=gfs05_ens
		echo "download-gfs $domain --run $run --only-variables precipitation,frozen_precipitation_percent --download-from-aws --concurrent 2"
		;;
	ecmwf)
		echo "download-ecmwf --domain ifs025_ensemble --run $run --only-variables snowfall_water_equivalent --source $(ecmwf_source) --concurrent 1 --download-concurrent 2"
		;;
	geps)
		echo "download-gem gem_global_ensemble --run $run --only-variables snowfall_water_equivalent --concurrent 2"
		;;
	esac
}

# GEPS: Environment Canada no longer publishes the land file this image builds its
# terrain from, so copy the finished one from the public data instead.
geps_terrain() {
	f=$DATA/cmc_gem_geps/static/HSURF.om
	[ -s "$f" ] && return 0
	mkdir -p "$(dirname "$f")"
	curl -sf -m 120 -o "$f.tmp" "$BUCKET_URL/cmc_gem_geps/static/HSURF.om" && mv "$f.tmp" "$f"
}

# What a system writes that nothing here reads, deleted after each run: the server works
# out `snowfall` from `snowfall_water_equivalent` alone. GEFS's precipitation (the input,
# 1.3 GB) and its precipitation_probability (which would hide the public data's, that
# the forecast API's blend reads, behind a copy with no past days), and every
# ensemble-mean folder (the app never asks for a mean; their time chunks pile up).
extras() {
	case $1 in
	gefs025 | gefs05)
		d=ncep_gefs025
		[ "$1" = gefs05 ] && d=ncep_gefs05
		echo "$d/precipitation $d/precipitation_probability ${d}_ensemble_mean"
		;;
	ecmwf) echo "ecmwf_ifs025_ensemble_mean" ;;
	geps) echo "cmc_gem_geps_ensemble_mean" ;;
	esac
}

# After each run: delete the extras, then, in case a future image writes more, any time
# chunk not written for KEEP_DAYS (it holds only past hours) and temporary files a
# stopped download left. Never `rolling.om` or `static/`, which the server serves.
prune() {
	for x in $(extras "$1"); do
		[ -e "$DATA/$x" ] && rm -rf "${DATA:?}/$x" && echo "$DATA/$x"
	done | while read -r gone; do log "removed ${gone#"$DATA"/} (not used)"; done
	for f in $(folders "$1"); do
		[ -d "$DATA/$f" ] || continue
		find "$DATA/$f" -type f -name 'chunk_*.om' -mmin +$((KEEP_DAYS * 1440)) -print -delete
		find "$DATA/$f" -type f -name '*~' -mmin +1440 -print -delete
	done | while read -r gone; do log "pruned ${gone#"$DATA"/}"; done
}

child=""
stop() {
	[ -n "$child" ] && kill "$child" 2>/dev/null
	log "stopping"
	exit 143
}
trap stop TERM INT

# Download one run: 0 on success. The downloader's output goes to <system>.log.
download() {
	sys=$1 run=$2
	out=$STATE/$sys.log
	mkdir -p "$STATE"
	started=$(now)
	# shellcheck disable=SC2046 # the argument list splits on spaces on purpose
	(cd "$(dirname "$BIN")" && exec nice -n 10 timeout "$TIMEOUT" "$BIN" $(command_for "$sys" "$run")) >"$out" 2>&1 &
	child=$!
	wait "$child"
	rc=$?
	child=""
	secs=$(($(now) - started))
	put "$sys" attempt_at "$(iso "$started")"
	if [ "$rc" = 0 ]; then
		put "$sys" run "$run"
		put "$sys" done_at "$(iso "$(now)")"
		put "$sys" seconds "$secs"
		drop "$sys" error
		drop "$sys" retry_at
		log "$sys $run done in ${secs}s"
		prune "$sys"
		put "$sys" size_kb "$(size_kb "$sys")"
		return 0
	fi
	if [ "$rc" = 124 ]; then
		why="timed out after $TIMEOUT"
	else
		why=$(grep -E '\[ (ERROR|CRITICAL) \]|[Ee]rror' "$out" | tail -n 1)
		[ -n "$why" ] || why=$(tail -n 1 "$out")
		why="exit $rc: $why"
	fi
	wait_s=$RETRY_AFTER_S
	if grep -qE 'SlowDown|Too Many Requests|HTTP 429|HTTP 503|status 503|code: 503' "$out"; then
		wait_s=$THROTTLED_AFTER_S
		why="throttled upstream, waiting an hour: $why"
	fi
	if [ "$sys" = ecmwf ]; then
		if [ "$(ecmwf_source)" = aws ]; then put ecmwf source ecmwf; else put ecmwf source aws; fi
	fi
	put "$sys" error "$(echo "$why" | cut -c1-300)"
	put "$sys" retry_at "$(($(now) + wait_s))"
	log "$sys $run FAILED after ${secs}s: $why (full output in ensembles/$sys.log)"
	return 1
}

check() {
	sys=$1
	retry_at=$(get "$sys" retry_at)
	if [ -n "$retry_at" ] && [ "$(now)" -lt "$retry_at" ]; then
		return 0
	fi
	run=$(newest_complete "$sys") || return 0
	last=$(get "$sys" run)
	if [ -n "$last" ] && [ "$run" -le "$last" ]; then
		return 0
	fi
	free=$(free_kb)
	if [ "$free" -lt $((MIN_FREE_GB * 1048576)) ]; then
		put "$sys" error "skipped $run: only $((free / 1048576)) GB free (ENSEMBLES_MIN_FREE_GB=$MIN_FREE_GB)"
		log "$sys: skipped $run, only $((free / 1048576)) GB free"
		return 0
	fi
	if [ "$sys" = geps ] && ! geps_terrain; then
		put geps error "couldn't copy HSURF.om from the public data"
		put geps retry_at "$(($(now) + RETRY_AFTER_S))"
		return 0
	fi
	log "$sys: downloading $run"
	download "$sys" "$run"
}

# JSON string: drop quotes, backslashes and control characters (error text is shown).
js() {
	if [ -z "$1" ]; then
		echo null
	else
		# shellcheck disable=SC1003 # tr deletes a quote and a backslash
		printf '"%s"' "$(printf '%s' "$1" | tr -d '"\\' | tr -c '[:print:]' ' ')"
	fi
}
jn() { if [ -z "$1" ]; then echo null; else echo "$1"; fi; }

write_status() {
	tmp=$STATE/status.json.tmp
	{
		printf '{"updated": %s, "free_kb": %s, "min_free_gb": %s, "keep_days": %s, "systems": {' \
			"$(js "$(iso "$(now)")")" "$(free_kb)" "$MIN_FREE_GB" "$KEEP_DAYS"
		sep=""
		for sys in $SYSTEMS; do
			err=$(get "$sys" error)
			retry=$(get "$sys" retry_at)
			[ -n "$retry" ] && retry=$(iso "$retry")
			ok=true
			[ -n "$err" ] && ok=false
			[ -z "$(get "$sys" run)" ] && [ -z "$err" ] && ok=null
			printf '%s"%s": {"folders": "%s", "run": %s, "done_at": %s, "seconds": %s, "attempt_at": %s, "ok": %s, "error": %s, "retry_at": %s, "size_kb": %s}' \
				"$sep" "$sys" "$(folders "$sys")" "$(js "$(get "$sys" run)")" "$(js "$(get "$sys" done_at)")" \
				"$(jn "$(get "$sys" seconds)")" "$(js "$(get "$sys" attempt_at)")" "$ok" "$(js "$err")" \
				"$(js "$retry")" "$(jn "$(get "$sys" size_kb)")"
			sep=", "
		done
		printf '}}\n'
	} >"$tmp" && mv "$tmp" "$STATE/status.json"
}

# One line per UTC day, for watching growth: free disk, the server's cache, each system.
disk_log() {
	day=$(date -u -d "@$(now)" +%Y-%m-%d)
	f=$STATE/disk.log
	[ -f "$f" ] && grep -q "^$day " "$f" && return 0
	line="$day free_gb=$(($(free_kb) / 1048576))"
	[ -f "$DATA/cache.bin" ] && line="$line cache_mb=$(($(du -sk "$DATA/cache.bin" | cut -f1) / 1024))"
	total=0
	for sys in $SYSTEMS; do
		kb=$(size_kb "$sys")
		total=$((total + kb))
		line="$line $sys=$((kb / 1024))MB"
	done
	line="$line ensembles_mb=$((total / 1024))"
	echo "$line" >>"$f"
	tail -n 90 "$f" >"$f.tmp" && mv "$f.tmp" "$f"
}

main() {
	mkdir -p "$STATE"
	log "watching $SYSTEMS every ${CHECK_EVERY_S}s; skipping downloads below ${MIN_FREE_GB} GB free"
	while :; do
		for sys in $SYSTEMS; do
			check "$sys"
		done
		write_status
		disk_log
		[ "${ENSEMBLES_ONCE:-0}" = 1 ] && return 0
		sleep "$CHECK_EVERY_S" &
		child=$!
		wait "$child"
		child=""
	done
}

# Sourced with ENSEMBLES_LIB=1 (the tests), only the functions are defined.
[ "${ENSEMBLES_LIB:-0}" = 1 ] || main
