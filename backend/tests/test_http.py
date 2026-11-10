from __future__ import annotations

import gzip
import json
import os
import time
from pathlib import Path

import httpx
import pytest

from snowwatch.http import Fetcher, FetchError, prune_raw


def make(handler, **kw):  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    f = Fetcher(
        user_agent="snowwatch-test (me@example.com)",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kw,
    )
    return f, sleeps


def test_429_waits_65s_then_succeeds() -> None:
    calls = iter([429, 200])

    def handler(req: httpx.Request) -> httpx.Response:
        code = next(calls)
        return httpx.Response(code, json={"ok": code == 200})

    f, sleeps = make(handler)
    assert f.get_json("https://x.test/a", source="t", weight=2.5) == {"ok": True}
    assert sleeps == [65.0]
    assert f.calls[0].tries == 2 and f.total_weight == 2.5
    assert f.rate_limited == 1


def test_server_errors_back_off_then_raise() -> None:
    f, sleeps = make(lambda req: httpx.Response(503), tries=3)
    with pytest.raises(FetchError, match="after 3 tries"):
        f.get_json("https://x.test/a", source="t")
    assert sleeps == [2, 5, 8]


def test_timeouts_are_retried() -> None:
    state = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, json=[1])

    f, sleeps = make(handler)
    assert f.get_json("https://x.test/a", source="t") == [1]
    assert sleeps == [2]


def test_client_errors_fail_at_once_with_reason() -> None:
    f, sleeps = make(
        lambda req: httpx.Response(400, json={"error": True, "reason": "Invalid model"})
    )
    with pytest.raises(FetchError, match="Invalid model"):
        f.get_json("https://x.test/a", source="t")
    assert sleeps == []


def test_open_meteo_error_body_raises() -> None:
    f, _ = make(lambda req: httpx.Response(200, json={"error": True, "reason": "bad"}))
    with pytest.raises(FetchError, match="bad"):
        f.get_json("https://x.test/a", source="t")


def test_user_agent_and_params_are_sent() -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["ua"] = req.headers["user-agent"]
        seen["q"] = req.url.params["point"]
        return httpx.Response(200, json={})

    f, _ = make(handler)
    f.get_json("https://x.test/a", {"point": "1,2"}, source="t")
    assert seen == {"ua": "snowwatch-test (me@example.com)", "q": "1,2"}


def test_raw_cache_written_and_pruned(tmp_path: Path) -> None:
    f, _ = make(lambda req: httpx.Response(200, json={"v": 1}), raw_dir=tmp_path)
    f.get_json("https://x.test/a", source="open-meteo", cache_key="crystal")
    files = list(tmp_path.rglob("*.json.gz"))
    assert len(files) == 1 and files[0].parent == tmp_path / "open-meteo" / "crystal"
    assert json.loads(gzip.decompress(files[0].read_bytes())) == {"v": 1}
    old = time.time() - 25 * 3600
    os.utime(files[0], (old, old))
    assert prune_raw(tmp_path, max_age_h=24) == 1
    assert not list(tmp_path.rglob("*.json.gz"))


def test_only_nws_gets_the_contact_details() -> None:
    import httpx

    from snowwatch.http import Fetcher

    seen: dict[str, str] = {}

    def answer(req: httpx.Request) -> httpx.Response:
        seen[req.url.host] = req.headers["user-agent"]
        return httpx.Response(200, json={})

    with Fetcher(
        user_agent="snowwatch/1",
        contact_user_agent="snowwatch/1 (me@example.com)",
        transport=httpx.MockTransport(answer),
    ) as f:
        f.get_json("https://api.weather.gov/points/1,2", source="nws")
        f.get_json("https://api.open-meteo.com/v1/forecast", source="om")
    assert seen == {
        "api.weather.gov": "snowwatch/1 (me@example.com)",
        "api.open-meteo.com": "snowwatch/1",
    }


def test_public_errors_lose_their_query_strings() -> None:
    from snowwatch.http import strip_queries

    msg = "HTTP 400 bad (https://api.example.com/v1/x?lat=1&key=secret)"
    assert strip_queries(msg) == "HTTP 400 bad (https://api.example.com/v1/x)"
