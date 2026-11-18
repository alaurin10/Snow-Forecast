"""Live webcam video that the location page can play in place.

Only players from a short list of webcam hosts are accepted: the site's Content
Security Policy lets exactly these hosts into a frame (`frame_hosts`), and each link is
rewritten to the host's own embed address, so whatever the owner pastes (a watch page,
a share link, an embed link) plays the same way. Anything else stays a plain link.

The frontend's `webcams.ts` reads links the same way; keep the two in step.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from snowwatch.urls import is_http_url

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_CHANNEL = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_YT_HOSTS = {"youtube.com", "m.youtube.com", "youtube-nocookie.com"}
_OZOLIO_ID = re.compile(r"^EMB_[A-Z0-9]{4,40}$")

# Hosts a webcam player may load in a frame. CamStreamer's embed redirects to
# YouTube's own player (www.youtube.com/embed), so that host is listed too.
frame_hosts: tuple[str, ...] = (
    "https://www.youtube-nocookie.com",
    "https://www.youtube.com",
    "https://player.brownrice.com",
    "https://camstreamer.com",
    "https://*.roundshot.com",
    "https://relay.ozolio.com",
)


def _host(u: str) -> str:
    h = (urlsplit(u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _youtube(u: str) -> str | None:
    parts = urlsplit(u)
    host = _host(u)
    segs = [s for s in parts.path.split("/") if s]
    vid: str | None = None
    if host == "youtu.be" and segs:
        vid = segs[0]
    elif host in _YT_HOSTS:
        if segs[:1] == ["watch"]:
            vid = (parse_qs(parts.query).get("v") or [""])[0]
        elif len(segs) >= 2 and segs[0] in ("embed", "live", "shorts", "v"):
            if segs[0] == "embed" and segs[1] == "live_stream":
                ch = (parse_qs(parts.query).get("channel") or [""])[0]
                return _channel(ch)
            vid = segs[1]
        elif len(segs) >= 3 and segs[0] == "channel" and segs[2] == "live":
            return _channel(segs[1])
    if vid and _YT_ID.match(vid):
        return f"https://www.youtube-nocookie.com/embed/{vid}"
    return None


def _channel(ch: str) -> str | None:
    # A channel's current live stream: only YouTube's main host serves this form.
    if _YT_CHANNEL.match(ch):
        return f"https://www.youtube.com/embed/live_stream?channel={ch}"
    return None


def _brownrice(u: str) -> str | None:
    parts = urlsplit(u)
    host = _host(u)
    if not host.endswith("brownrice.com"):
        return None
    segs = [s for s in parts.path.split("/") if s]
    name = ""
    if host == "player.brownrice.com" and len(segs) == 2 and segs[0] in ("embed", "snapshot"):
        name = segs[1]
    elif re.match(r"^live\d+p?\.brownrice\.com$", host):
        name = (parse_qs(parts.query).get("sn") or [""])[0]
    return f"https://player.brownrice.com/embed/{name}" if _NAME.match(name) else None


def _camstreamer(u: str) -> str | None:
    segs = [s for s in urlsplit(u).path.split("/") if s]
    named = len(segs) == 2 and segs[0] == "embed" and _NAME.match(segs[1])
    if _host(u) == "camstreamer.com" and named:
        return f"https://camstreamer.com/embed/{segs[1]}"
    return None


def _roundshot(u: str) -> str | None:
    parts = urlsplit(u)
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and host.endswith(".roundshot.com") and not parts.port:
        return parts._replace(fragment="").geturl()
    return None


def _ozolio(u: str) -> str | None:
    parts = urlsplit(u)
    if _host(u) != "relay.ozolio.com" or parts.path != "/pub.api":
        return None
    oid = (parse_qs(parts.query).get("oid") or [""])[0]
    if _OZOLIO_ID.match(oid):
        return f"https://relay.ozolio.com/pub.api?cmd=embed&oid={oid}"
    return None


def embed_url(link: str | None) -> str | None:
    """The player address for a link to a supported webcam host, or None."""
    if not link or not is_http_url(link):
        return None
    for read in (_youtube, _brownrice, _camstreamer, _roundshot, _ozolio):
        if got := read(link):
            return got
    return None


def check_video_url(value: str) -> str:
    """Pydantic validator: a supported player link, stored as its embed address."""
    got = embed_url(value)
    if got is None:
        raise ValueError(
            "live video must be a YouTube, Brownrice, CamStreamer, Roundshot or Ozolio link"
        )
    return got
