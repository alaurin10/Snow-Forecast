"""Push alert subscriptions. Any signed-in viewer may subscribe their own device."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from snowwatch import push
from snowwatch.api.admin import RW
from snowwatch.api.auth import CurrentViewer
from snowwatch.push import PushOut, PushSubscription, SubscribeIn
from snowwatch.settings import Settings


def make_push_router() -> APIRouter:
    router = APIRouter(prefix="/api/push")

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
    def subscribe(body: SubscribeIn, request: Request, conn: RW, viewer: CurrentViewer) -> PushOut:
        settings_of(request)
        push.subscribe(conn, body, viewer.email)
        return PushOut(ok=True)

    @router.post("/unsubscribe", response_model=PushOut)
    def unsubscribe(body: PushSubscription, conn: RW) -> PushOut:
        return PushOut(ok=push.unsubscribe(conn, body.endpoint))

    @router.post("/test", response_model=PushOut)
    def test(body: PushSubscription, request: Request, conn: RW) -> PushOut:
        settings = settings_of(request)
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
                "url": "/more",
                "tag": "test",
            },
            sender,
        )
        return PushOut(ok=ok, sent=int(ok), detail=None if ok else "the push service refused it")

    return router
