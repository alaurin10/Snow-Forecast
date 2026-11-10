"""Push alert subscriptions. Any visitor may subscribe their own device.

These endpoints are public, so each is rate limited per visitor, subscriptions
must point at a real browser push service (see push.is_push_service), and the
server holds at most PUSH_MAX_SUBSCRIPTIONS of them.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from snowwatch import push
from snowwatch.api.admin import RW
from snowwatch.api.ratelimit import RateLimiter
from snowwatch.push import AlertPrefs, Endpoint, PushOut, SubscribeIn
from snowwatch.settings import Settings


def make_push_router() -> APIRouter:
    router = APIRouter(prefix="/api/push")
    # Saving choices: a burst of 10, then one a minute. Tests: 3, then one per 10 min.
    saves = RateLimiter(rate=1 / 60, burst=10)
    tests = RateLimiter(rate=1 / 600, burst=3)

    def settings_of(request: Request) -> Settings:
        settings: Settings = request.app.state.settings
        if not push.enabled(settings):
            raise HTTPException(404, "push alerts are not set up on this server")
        return settings

    @router.get("/key")
    def key(request: Request) -> dict[str, str]:
        """The VAPID public key the browser subscribes with."""
        return {"key": settings_of(request).vapid_public_key}

    @router.post("/subscribe", response_model=PushOut)
    def subscribe(body: SubscribeIn, request: Request, conn: RW) -> PushOut:
        settings = settings_of(request)
        saves.check(request)
        try:
            push.subscribe(conn, body, max_subs=settings.push_max_subscriptions)
        except push.SubscriptionLimitError as e:
            raise HTTPException(503, "alerts are full on this server; try again later") from e
        return PushOut(ok=True)

    @router.post("/prefs", response_model=AlertPrefs)
    def prefs(body: Endpoint, request: Request, conn: RW) -> AlertPrefs:
        """The saved choices of this device's subscription."""
        settings_of(request)
        saves.check(request, cost=0.2)
        found = push.prefs(conn, body.endpoint)
        if found is None:
            raise HTTPException(404, "this device isn't subscribed")
        return found

    @router.post("/unsubscribe", response_model=PushOut)
    def unsubscribe(body: Endpoint, request: Request, conn: RW) -> PushOut:
        saves.check(request)
        return PushOut(ok=push.unsubscribe(conn, body.endpoint))

    @router.post("/test", response_model=PushOut)
    def test(body: Endpoint, request: Request, conn: RW) -> PushOut:
        settings = settings_of(request)
        tests.check(request)
        sub = next((s for s in push.subscriptions(conn) if s.endpoint == body.endpoint), None)
        if sub is None:
            raise HTTPException(404, "this device isn't subscribed")
        sender = getattr(request.app.state, "push_sender", push.webpush_sender)
        ok = push.send(
            conn,
            settings,
            sub,
            {
                "title": "Snow Watch alerts are on",
                "body": "You'll hear about powder days and storms here.",
                "url": "/settings",
                "tag": "test",
            },
            sender,
        )
        return PushOut(ok=ok, sent=int(ok), detail=None if ok else "the push service refused it")

    return router
