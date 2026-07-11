"""Mints the LiveKit access token a widget visitor uses to join a room.

Also sets the job-dispatch metadata the voice runtime's agent worker reads
at session start (`voice_runtime/agent.py::_job_metadata`) — without the
`RoomAgentDispatch`, LiveKit never dispatches the `voice-runtime` agent into
the room and the visitor joins an empty room.
"""

import json
import uuid
from datetime import timedelta

from livekit.api import AccessToken, RoomAgentDispatch, RoomConfiguration, VideoGrants

from ..config import settings

VOICE_RUNTIME_AGENT_NAME = "voice-runtime"


def mint_widget_token(
    *, tenant_id: str, page_url: str | None = None, visitor_id: str | None = None
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
