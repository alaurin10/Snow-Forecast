"""Milestone 1b: the ensemble downloader script (docker/ensembles.sh) and what the app
reads from the volume it writes (snowwatch/ensembles.py)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from snowwatch import checks, ensembles
from snowwatch.http import Fetcher
from snowwatch.settings import REPO_ROOT
from snowwatch.store import repo
from tests.test_openmeteo_local import LOCAL, meta_and_local

SCRIPT = REPO_ROOT / "docker" / "ensembles.sh"
NOW = int(datetime(2026, 11, 27, 9, 10, tzinfo=UTC).timestamp())

# The script uses GNU date (as in the Open-Meteo image); skip where there's none.
pytestmark = pytest.mark.skipif(
    shutil.which("sh") is None
    or subprocess.run(["date", "-u", "-d", "@0"], capture_output=True).returncode != 0,
    reason="needs sh and GNU date",
)

# Upstream files that "exist": only the 00z runs are complete.
ONLY_00Z = 'exists() { case "$1" in *t00z*|*/00z/*|*/00/384/*) return 0 ;; esac; return 1; }'

STUB = """#!/bin/sh
# Stands in for the image's openmeteo-api: records its arguments, writes meta.json.
echo "$@" >> "$DATA/calls.txt"
[ -n "${STUB_FAIL:-}" ] && { echo "[ ERROR ] $STUB_FAIL"; exit 1; }
run=$(echo "$@" | sed 's/.*--run \\([0-9]*\\).*/\\1/')
for f in $STUB_FOLDERS; do
  mkdir -p "$DATA/$f/static" "$DATA/$f/snowfall/"
  echo '{"last_run_initialisation_time": 1795737600, "data_end_time": 1797130800}' \
    > "$DATA/$f/static/meta.json"
done
echo done
"""


def sh(script: str, data: Path, **env: str) -> subprocess.CompletedProcess[str]:
    """Source the script (functions only) in sh, then run `script`."""
    full = {
        **os.environ,
        "ENSEMBLES_LIB": "1",
        "ENSEMBLES_DATA": str(data),
        "ENSEMBLES_NOW": str(NOW),
        "DATA": str(data),
        **env,
    }
    return subprocess.run(
        ["sh", "-c", f". {SCRIPT}; {script}"],
        capture_output=True,
        text=True,
        env=full,
        timeout=60,
    )


def stub(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "openmeteo-api"
    exe.write_text(STUB)
    exe.chmod(0o755)
    return exe


def test_candidate_runs_newest_first(tmp_path: Path) -> None:
    out = sh("cycles geps; echo --; cycles gefs05", tmp_path).stdout.split("--")
    assert out[0].split() == ["2026112700", "2026112612"]
    assert out[1].split() == [
        "2026112706",
        "2026112700",
        "2026112618",
        "2026112612",
        "2026112606",
    ]


def test_markers_are_each_runs_last_step(tmp_path: Path) -> None:
    out = sh(
        "markers ecmwf 2026112700; markers ecmwf 2026112706; markers geps 2026112612;"
        " markers gefs05 2026112618",
        tmp_path,
    ).stdout.split()
    assert out[0].endswith("/20261127/00z/ifs/0p25/enfo/20261127000000-360h-enfo-ef.index")
    assert out[1].endswith("/20261127/06z/ifs/0p25/enfo/20261127060000-144h-enfo-ef.index")
    assert out[2].endswith(
        "/20261126/WXO-DD/ensemble/geps/grib2/raw/12/384/"
        "CMC_geps-raw_ASNOW_SFC_0_latlon0p5x0p5_2026112612_P384_allmbrs.grib2"
    )
    assert out[3].endswith("gefs.20261126/18/atmos/pgrb2ap5/gep30.t18z.pgrb2a.0p50.f384.idx")
    assert out[4].endswith("gefs.20261126/18/atmos/pgrb2bp5/gep30.t18z.pgrb2b.0p50.f384.idx")
    # After a failure on ECMWF's own server, its AWS mirror.
    out = sh("put ecmwf source aws; markers ecmwf 2026112700", tmp_path).stdout
    assert out.startswith("https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com/20261127/00z/")


def test_newest_complete_run_skips_unfinished_ones(tmp_path: Path) -> None:
    out = sh(f"{ONLY_00Z}; newest_complete gefs025; newest_complete ecmwf", tmp_path)
    assert out.stdout.split() == ["2026112700", "2026112700"]
    nothing = sh("exists() { return 1; }; newest_complete geps || echo none", tmp_path)
    assert nothing.stdout.strip() == "none"


def _pass(tmp_path: Path, data: Path, **env: str) -> subprocess.CompletedProcess[str]:
    exe = stub(tmp_path) if not (tmp_path / "bin").exists() else tmp_path / "bin/openmeteo-api"
    (data / "cmc_gem_geps" / "static").mkdir(parents=True, exist_ok=True)
    (data / "cmc_gem_geps" / "static" / "HSURF.om").write_bytes(b"x")
    return sh(
        f"{ONLY_00Z}; main",
        data,
        OPENMETEO_BIN=str(exe),
        ENSEMBLES_ONCE="1",
        ENSEMBLES_SYSTEMS="gefs025 geps",
        STUB_FOLDERS="ncep_gefs025 cmc_gem_geps",
        **env,
    )


def test_a_pass_downloads_each_new_run_once(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    first = _pass(tmp_path, data)
    assert first.returncode == 0, first.stderr
    calls = (data / "calls.txt").read_text().splitlines()
    assert calls == [
        "download-gfs gfs025_ens --run 2026112700 --only-variables "
        "precipitation,frozen_precipitation_percent --download-from-aws --concurrent 2",
        "download-gem gem_global_ensemble --run 2026112700 --only-variables "
        "snowfall_water_equivalent --concurrent 2",
    ]
    status = json.loads((data / "ensembles" / "status.json").read_text())
    assert status["systems"]["gefs025"]["run"] == "2026112700"
    assert status["systems"]["gefs025"]["ok"] is True
    assert status["systems"]["geps"]["error"] is None
    assert status["free_kb"] > 0 and status["min_free_gb"] == 5
    assert "downloading 2026112700" in first.stdout and "done in" in first.stdout
    # The downloader's own output goes to a file, not to docker's log.
    assert (data / "ensembles" / "gefs025.log").read_text().strip() == "done"
    assert "done\n" not in first.stdout
    # One disk line a day.
    assert len((data / "ensembles" / "disk.log").read_text().splitlines()) == 1

    second = _pass(tmp_path, data)
    assert second.returncode == 0
    assert len((data / "calls.txt").read_text().splitlines()) == 2  # nothing new
    assert len((data / "ensembles" / "disk.log").read_text().splitlines()) == 1


def test_a_failure_is_recorded_and_retried_later(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _pass(tmp_path, data, STUB_FAIL="SlowDown: Please reduce your request rate")
    status = json.loads((data / "ensembles" / "status.json").read_text())
    row = status["systems"]["gefs025"]
    assert row["ok"] is False and row["run"] is None
    assert "throttled upstream" in row["error"] and "SlowDown" in row["error"]
    assert row["retry_at"] == "2026-11-27T10:10:00Z"  # an hour after a throttle
    # Within the wait, no new attempt.
    _pass(tmp_path, data)
    assert len((data / "calls.txt").read_text().splitlines()) == 2
    # After it, the download goes ahead and clears the error.
    _pass(tmp_path, data, ENSEMBLES_NOW=str(NOW + 3700))
    status = json.loads((data / "ensembles" / "status.json").read_text())
    assert status["systems"]["gefs025"]["ok"] is True
    assert status["systems"]["gefs025"]["error"] is None


def test_ecmwf_switches_source_after_a_failure(tmp_path: Path) -> None:
    exe = stub(tmp_path)
    out = sh(
        "download ecmwf 2026112700; ecmwf_source; command_for ecmwf 2026112700",
        tmp_path,
        OPENMETEO_BIN=str(exe),
        STUB_FAIL="boom",
        STUB_FOLDERS="",
    )
    lines = out.stdout.strip().splitlines()
    assert lines[-2] == "aws"
    assert "--source aws" in lines[-1]
    assert "--source ecmwf" in (tmp_path / "calls.txt").read_text()


def test_low_disk_skips_downloads(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _pass(tmp_path, data, ENSEMBLES_MIN_FREE_GB="999999")
    assert not (data / "calls.txt").exists()
    status = json.loads((data / "ensembles" / "status.json").read_text())
    assert "GB free (ENSEMBLES_MIN_FREE_GB=999999)" in status["systems"]["geps"]["error"]


def test_prune_keeps_only_what_the_server_serves(tmp_path: Path) -> None:
    old = NOW - 5 * 86400
    files = {
        "ncep_gefs05/snowfall_water_equivalent/rolling.om": old,
        "ncep_gefs05/static/HSURF.om": old,
        "ncep_gefs05/static/meta.json": NOW,
        "ncep_gefs05/precipitation/rolling.om": NOW,
        "ncep_gefs05/precipitation_probability/chunk_345.om": NOW,
        "ncep_gefs05_ensemble_mean/precipitation/chunk_345.om": NOW,
        "ncep_gefs05/other/chunk_344.om": old,
        "ncep_gefs05/other/chunk_345.om": NOW,
        "ncep_gefs05/snowfall_water_equivalent/rolling.om~": old,
        "ncep_gefs025/precipitation/rolling.om": NOW,  # another system's: untouched
    }
    for name, mtime in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        os.utime(p, (mtime, mtime))
    out = sh("prune gefs05", tmp_path)
    assert out.returncode == 0, out.stderr
    left = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()}
    assert left == {
        "ncep_gefs05/snowfall_water_equivalent/rolling.om",
        "ncep_gefs05/static/HSURF.om",
        "ncep_gefs05/static/meta.json",
        "ncep_gefs05/other/chunk_345.om",
        "ncep_gefs025/precipitation/rolling.om",
    }
    assert not (tmp_path / "ncep_gefs05_ensemble_mean").exists()
    assert "removed ncep_gefs05/precipitation (not used)" in out.stdout
    assert "pruned ncep_gefs05/other/chunk_344.om" in out.stdout


def test_status_json_escapes_error_text(tmp_path: Path) -> None:
    out = sh(
        """SYSTEMS=geps; mkdir -p "$DATA/ensembles"; put geps error 'bad "quote" \\ here';"""
        ' write_status; cat "$DATA/ensembles/status.json"',
        tmp_path,
    )
    data = json.loads(out.stdout)
    assert data["systems"]["geps"]["error"] == "bad quote  here"
    assert data["systems"]["geps"]["ok"] is False


# --- What the app reads ---------------------------------------------------------------


def _meta(data: Path, folder: str, init: datetime, end: datetime) -> None:
    p = data / folder / "static" / "meta.json"
    p.parent.mkdir(parents=True)
    p.write_text(
        json.dumps(
            {
                "last_run_initialisation_time": init.timestamp(),
                "data_end_time": end.timestamp(),
            }
        )
    )


def test_domain_run_reads_meta_json(tmp_path: Path) -> None:
    now = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
    _meta(
        tmp_path,
        "cmc_gem_geps",
        datetime(2026, 11, 27, tzinfo=UTC),
        datetime(2026, 12, 13, tzinfo=UTC),
    )
    run = ensembles.domain_run(tmp_path, "cmc_gem_geps")
    assert run is not None and run.age_h(now) == 9 and run.reach_h(now) == 375
    assert ensembles.domain_run(tmp_path, "ncep_gefs05") is None


def test_status_lines(tmp_path: Path) -> None:
    now = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
    ok, lines = ensembles.status_lines(tmp_path / "missing", now=now, fallback_dir=tmp_path)
    assert ok and "not downloaded here (not mounted" in lines[0]
    assert lines[-1].startswith("disk ") and "GB free" in lines[-1]

    _meta(
        tmp_path,
        "cmc_gem_geps",
        datetime(2026, 11, 27, tzinfo=UTC),
        datetime(2026, 12, 13, tzinfo=UTC),
    )
    _meta(
        tmp_path,
        "ncep_gefs025",
        datetime(2026, 11, 26, 12, tzinfo=UTC),
        datetime(2026, 12, 6, 12, tzinfo=UTC),
    )
    (tmp_path / "ensembles").mkdir()
    (tmp_path / "ensembles" / "status.json").write_text(
        json.dumps(
            {
                "updated": "2026-11-27T08:55:00Z",
                "systems": {
                    "geps": {"run": "2026112700", "seconds": 85, "size_kb": 80000},
                    "gefs025": {"error": "exit 1: boom", "retry_at": "2026-11-27T09:30:00Z"},
                },
            }
        )
    )
    ok, lines = ensembles.status_lines(tmp_path, now=now)
    text = "\n".join(lines)
    assert ok
    assert "downloader last checked 5 min ago" in text
    assert "GEPS           run 2026-11-27 00z, 9.0 h old, reaches 375 h ahead, took 85 s" in text
    assert "GEFS 0.25°     run 2026-11-26 12z, 21.0 h old (STALE)" in text
    assert "last error: exit 1: boom (retrying at 2026-11-27T09:30:00Z)" in text
    assert "ECMWF" not in text  # never downloaded: not listed


def test_low_disk_is_not_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ensembles, "free_gb", lambda *p: 7.5)
    ok, lines = ensembles.status_lines(tmp_path)
    assert not ok and "LOW: 7.5 GB free" in lines[-1]
    # ... and makes `openmeteo status` NOT OK.
    f = Fetcher(user_agent="t", transport=httpx.MockTransport(meta_and_local), tries=1)
    good, out = checks.openmeteo_status(
        LOCAL, True, 10_000, repo.Usage(), f, cpu=(True, "AVX2"), ensembles=(ok, lines)
    )
    assert not good and out[-1] == "NOT OK" and any("LOW: 7.5" in line for line in out)
