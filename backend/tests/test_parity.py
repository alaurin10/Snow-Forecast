"""The ported analysis must reproduce the prototype on the same data.

docs/reference/pull.py runs as-is (its `fetch` swapped for the captured
`proto_*` responses) and its periods, consensus and windows are compared with
the new modules run in the prototype's configuration: the four global models,
no short-range models, model snowfall, the blend in the first four periods.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from snowwatch.analysis import ensemble as ens
from snowwatch.analysis.consensus import period_consensus
from snowwatch.analysis.periods import build_periods
from snowwatch.analysis.series import (
    ensemble_members,
    mean,
    parse_point,
    parse_points,
    split_models,
)
from snowwatch.capture import load_fixture
from snowwatch.settings import REPO_ROOT
from tests.helpers import FIXTURES

CM2IN = 1 / 2.54
LOCS = ["crystal", "snoqualmie", "rainy", "whistler", "revelstoke", "sunshine"]


@pytest.fixture(scope="module")
def pull(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    path = REPO_ROOT / "docs" / "reference" / "pull.py"
    spec = importlib.util.spec_from_file_location("prototype_pull", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    argv = sys.argv
    sys.argv = ["pull.py", str(tmp_path_factory.mktemp("proto-out"))]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.argv = argv
    return module


def proto_inputs(loc_id: str) -> tuple[Any, Any, dict[str, Any]]:
    folder = FIXTURES / loc_id
    det = load_fixture(folder / "proto_det.json.gz")
    multi = load_fixture(folder / "proto_multi.json.gz")
    ensembles = {
        m: load_fixture(folder / f"proto_ens_{m}.json.gz") for m in ("gfs_seamless", "ecmwf_ifs025")
    }
    return det, multi, ensembles


@pytest.mark.parametrize("loc_id", LOCS)
def test_periods_consensus_and_windows_match(pull: ModuleType, loc_id: str) -> None:
    det, multi, ensembles = proto_inputs(loc_id)
    loc = next(x for x in pull.LOCATIONS if x["id"] == loc_id)
    pull.fetch = lambda _loc: (det, multi, ensembles)
    proto = pull.build(loc)

    mid = parse_points(det)[1]
    tz = ZoneInfo(mid.tz)
    cur = det[1]["current"]["time"][:13] + ":00"
    now_h = int(datetime.fromisoformat(cur).replace(tzinfo=tz).timestamp())
    today = datetime.fromisoformat(cur).date()
    temps = mid.get("temperature_2m")
    hours = sorted(h for h, v in temps.items() if h >= now_h and v is not None)
    periods = build_periods(hours, tz, today)

    assert [p.key for p in periods] == [p["key"] for p in proto["periods"]]
    assert [p.label for p in periods] == [p["label"] for p in proto["periods"]]
    assert [len(p.hours) for p in periods] == [p["hours"] for p in proto["periods"]]

    models = {
        m: v["snowfall"] for m, v in split_models(parse_point(multi), pull.MODELS.values()).items()
    }
    blend = mid.get("snowfall")
    members = ens.pooled({s: ensemble_members(parse_point(e)) for s, e in ensembles.items()})
    for j, (p, pp) in enumerate(zip(periods, proto["periods"], strict=True)):
        totals = ens.member_totals(members, p.hours)
        c = period_consensus(
            p.hours, models, blend=blend, early=j < 4, ens_mean=mean(totals) if totals else None
        )
        assert c.basis == pp["basis"], p.key
        assert c.value is not None
        # The prototype rounds hourly blend values to 0.01 in before summing.
        assert c.value * CM2IN == pytest.approx(pp["cons"], abs=0.06), p.key
        st = ens.stats(totals, 1)
        if pp["ens_p50"] is not None and st is not None:
            assert (st.p50 or 0) * CM2IN == pytest.approx(pp["ens_p50"], abs=0.051), p.key
            assert (st.p90 or 0) * CM2IN == pytest.approx(pp["ens_p90"], abs=0.051), p.key

    for name, (a, b) in {"next5": (0, 10), "d6_10": (10, 20)}.items():
        window_hours = [h for p in periods[a:b] for h in p.hours]
        totals = [t * CM2IN for t in ens.member_totals(members, window_hours)]
        pw = proto[name]
        st = ens.stats(totals, 1)
        assert st is not None
        assert st.p10 == pytest.approx(pw["p10"], abs=0.051)
        assert st.p50 == pytest.approx(pw["p50"], abs=0.051)
        assert st.p90 == pytest.approx(pw["p90"], abs=0.051)
        for x in (1, 6, 12):
            assert ens.exceedance(totals, x) == pytest.approx(pw[f"prob{x}"], abs=1)
