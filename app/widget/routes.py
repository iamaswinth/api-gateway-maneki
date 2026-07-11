"""Anonymous widget-facing token issuance — the actual security boundary for
tenant isolation. Every rejection here is a request that never reaches the
voice runtime, so no STT/LLM/TTS cost is incurred for an unauthorized caller.

No rate limiting yet (that's app/ratelimit/, wired in separately) — this
endpoint is deliberately testable in isolation first.
"""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..config import settings
from .livekit_token import mint_widget_token
from .tenant_cache import get_cached_tenant

router = APIRouter(prefix="/widget", tags=["widget"])


class WidgetTokenRequest(BaseModel):
    site_id: str
    page_url: Optional[str] = None
    visitor_id: Optional[str] = None


class WidgetTokenResponse(BaseModel):
    token: str
    livekit_url: str
    room: str


@router.post("/token", response_model=WidgetTokenResponse)
async def issue_widget_token(
    data: WidgetTokenRequest, origin: Optional[str] = Header(default=None)
) -> WidgetTokenResponse:
    tenant = await get_cached_tenant(data.site_id)
    if tenant is None or not tenant.published:
        raise HTTPException(status_code=403, detail="Site not published")
    if origin != tenant.allowed_origin:
        raise HTTPException(status_code=403, detail="Origin not allowed")

    token, room = mint_widget_token(
        tenant_id=data.site_id, page_url=data.page_url, visitor_id=data.visitor_id
    )
    return WidgetTokenResponse(token=token, livekit_url=settings.livekit_url, room=room)
