from __future__ import annotations

import pytest
from pydantic import ValidationError

from snowwatch.locations.service import load_yaml
from tests.conftest import SEED, make_location


def test_seed_file_has_six_valid_locations() -> None:
    locs = load_yaml(SEED)
    assert [loc.id for loc in locs] == [
        "crystal",
        "snoqualmie",
        "rainy",
        "whistler",
        "revelstoke",
        "sunshine",
    ]
    assert [loc.sort_order for loc in locs] == list(range(6))
    assert {loc.kind for loc in locs} == {"resort", "backcountry"}
    crystal = locs[0]
    assert crystal.band("mid").elev_m == 1800
    assert crystal.avy is not None and crystal.avy.zone_id == "3023"


def test_bands_must_be_base_mid_summit_in_order() -> None:
    loc = make_location()
    bands = [b.model_dump() for b in loc.bands]
    with pytest.raises(ValidationError, match="exactly"):
        make_location(bands=[bands[1], bands[0], bands[2]])
    with pytest.raises(ValidationError, match="exactly"):
        make_location(bands=bands[:2])


def test_band_elevations_must_rise() -> None:
    bands = [b.model_dump() for b in make_location().bands]
    bands[1]["elev_m"] = 900
    with pytest.raises(ValidationError, match="rise"):
        make_location(bands=bands)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "Has Spaces"),
        ("id", "x"),
        ("tz", "Mars/Olympus"),
        ("snotel", "642-WA"),
        ("country", "FR"),
    ],
)
def test_invalid_fields_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        make_location(**{field: value})


def test_coordinates_are_range_checked() -> None:
    bands = [b.model_dump() for b in make_location().bands]
    bands[0]["lat"] = 95
    with pytest.raises(ValidationError):
        make_location(bands=bands)


def test_links_must_be_http() -> None:
    import pytest
    from pydantic import ValidationError

    from tests.conftest import make_location

    assert make_location(links={"Site": "https://example.com"}).links
    for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://x", "https://", " https://a.b"):
        with pytest.raises(ValidationError):
            make_location(links={"Site": bad})
        with pytest.raises(ValidationError):
            make_location(webcams=[{"name": "Cam", "url": bad}])
    with pytest.raises(ValidationError):
        make_location(name="x" * 81)


def test_upstream_links_are_dropped_not_shown() -> None:
    from snowwatch.avalanche import AvalancheDoc

    doc = AvalancheDoc(
        provider="nac",
        center=None,
        center_id=None,
        zone=None,
        link="javascript:alert(1)",
        issued_at=None,
        expires_at=None,
    )
    assert doc.link is None


def test_old_stored_rows_with_bad_links_still_load(conn: object) -> None:
    import sqlite3

    from snowwatch.locations import service
    from tests.conftest import make_location

    assert isinstance(conn, sqlite3.Connection)
    service.upsert_location(conn, make_location(), max_locations=25)
    with conn:
        conn.execute(
            "UPDATE locations SET links_json = ?, webcams_json = ?",
            (
                '{"Bad": "javascript:alert(1)", "Good": "https://ok.example"}',
                '[{"name": "x", "url": "javascript:1"}]',
            ),
        )
    (loc,) = service.list_locations(conn)
    assert loc.links == {"Good": "https://ok.example"} and loc.webcams == []


def test_webcam_video_links_become_embed_addresses() -> None:
    import pytest
    from pydantic import ValidationError

    from snowwatch.webcams import embed_url
    from tests.conftest import make_location

    nocookie = "https://www.youtube-nocookie.com/embed/vhO8nNqg9iw"
    for link in (
        "https://www.youtube.com/watch?v=vhO8nNqg9iw",
        "https://youtube.com/watch?v=vhO8nNqg9iw&t=3",
        "https://m.youtube.com/watch?v=vhO8nNqg9iw",
        "https://youtu.be/vhO8nNqg9iw?si=abc",
        "https://www.youtube.com/live/vhO8nNqg9iw",
        "https://www.youtube.com/embed/vhO8nNqg9iw?autoplay=1",
        nocookie,
    ):
        assert embed_url(link) == nocookie, link
    channel = "UCabcdefghijklmnopqrstuv"
    assert embed_url(f"https://www.youtube.com/channel/{channel}/live") == (
        f"https://www.youtube.com/embed/live_stream?channel={channel}"
    )
    br = "https://player.brownrice.com/embed/whistlerpeak"
    assert embed_url(br) == br
    assert embed_url("https://player.brownrice.com/snapshot/whistlerpeak") == br
    assert embed_url("https://live9.brownrice.com/?sn=whistlerpeak&em=1") == br
    cs = "https://camstreamer.com/embed/PZyoJBnQWsgYwwHoRAmjihHkxPi4lD8yZSOFkJZk"
    assert embed_url(cs + "?enablejsapi=1") == cs
    assert embed_url("https://crystal.roundshot.com/#/") == "https://crystal.roundshot.com/"
    for bad in (
        "https://www.youtube.com/@TheSummitatSnoqualmie",
        "https://www.youtube.com/watch?v=short",
        "https://evil.example/embed/vhO8nNqg9iw",
        "https://youtube.com.evil.example/watch?v=vhO8nNqg9iw",
        "http://crystal.roundshot.com/",
        "https://roundshot.com.evil.example/",
        "https://www.nps.gov/webcams-mora/mountain.jpg",
        "javascript:alert(1)",
    ):
        assert embed_url(bad) is None, bad

    cam = make_location(
        webcams=[
            {"name": "Cam", "url": "https://x.example", "video_url": "https://youtu.be/vhO8nNqg9iw"}
        ]
    ).webcams[0]
    assert cam.video_url == nocookie
    with pytest.raises(ValidationError):
        make_location(
            webcams=[
                {"name": "Cam", "url": "https://x.example", "video_url": "https://x.example/v"}
            ]
        )
