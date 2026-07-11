"""LiveKit room lifecycle webhooks — the concurrency-limit decrementer.

Verifies the request signature (LiveKit signs webhook payloads with the same
API key/secret used to mint tokens) before touching any state. This is the
source of truth for "a session actually started/ended" — /widget/token only
checks the count, it never increments it directly, so a token that's issued
but never joined doesn't consume a concurrency slot.
"""

from fastapi import APIRouter, Header, HTTPException, Request
from livekit.api import TokenVerifier, WebhookReceiver

from ..config import settings
from ..ratelimit import sessions
from ..redis_client import get_redis
from ..widget.livekit_token import parse_tenant_id

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _receiver() -> WebhookReceiver:
    return WebhookReceiver(TokenVerifier(settings.livekit_api_key, settings.livekit_api_secret))


@router.post("/livekit")
async def livekit_webhook(request: Request, authorization: str = Header(default="")) -> dict:
    body = await request.body()
    try:
        event = _receiver().receive(body.decode("utf-8"), authorization)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid webhook signature: {exc}")

    room_name = event.room.name if event.room else ""
    tenant_id = parse_tenant_id(room_name) if room_name else None

    if tenant_id:
        redis = get_redis()
        if event.event == "room_started":
            await sessions.mark_room_started(redis, tenant_id, room_name)
        elif event.event == "room_finished":
            await sessions.mark_room_finished(redis, tenant_id, room_name)

    return {"status": "ok"}
