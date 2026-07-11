"""Mints the LiveKit access token a widget visitor uses to join a room.

Also sets the job-dispatch metadata the voice runtime's agent worker reads
at session start (`voice_runtime/agent.py::_job_metadata`) — without the
`RoomAgentDispatch`, LiveKit never dispatches the `voice-runtime` agent into
the room and the visitor joins an empty room.
"""

import json
import re
import uuid
from datetime import timedelta
from typing import Optional

from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants

from ..config import settings

VOICE_RUNTIME_AGENT_NAME = "voice-runtime"

# Matches "tenant-{tenant_id}-{uuid4}" — tenant_id may itself contain hyphens,
# so the uuid4's fixed 36-char shape at the end is what anchors the split
# (used by app/webhooks/routes.py to recover tenant_id from a room name).
_ROOM_NAME_RE = re.compile(
    r"^tenant-(?P<tenant_id>.+)-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def parse_tenant_id(room_name: str) -> Optional[str]:
    match = _ROOM_NAME_RE.match(room_name)
    return match.group("tenant_id") if match else None


def mint_widget_token(
    *,
    tenant_id: str,
    page_url: str | None = None,
    visitor_id: str | None = None,
    session_id: str | None = None,
) -> tuple[str, str]:
    """Returns (jwt, room_name)."""
    room_name = f"tenant-{tenant_id}-{uuid.uuid4()}"
    resolved_visitor_id = visitor_id or f"visitor-{uuid.uuid4()}"

    dispatch_metadata = {
        "tenant_id": tenant_id,
        "visitor_id": resolved_visitor_id,
    }
    if page_url:
        dispatch_metadata["page_url"] = page_url
    if session_id:
        dispatch_metadata["session_id"] = session_id

    token = (
        AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(resolved_visitor_id)
        .with_ttl(timedelta(seconds=settings.widget_token_ttl_seconds))
        .with_grants(VideoGrants(room_join=True, room=room_name))
        .with_room_config(
            RoomConfiguration(
                agents=[
                    RoomAgentDispatch(
                        agent_name=VOICE_RUNTIME_AGENT_NAME,
                        metadata=json.dumps(dispatch_metadata),
                    )
                ]
            )
        )
    )
    return token.to_jwt(), room_name
