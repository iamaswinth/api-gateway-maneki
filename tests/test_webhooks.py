"""POST /webhooks/livekit: signature verification + room-lifecycle wiring
into the concurrency counter (app/ratelimit/sessions.py).
"""

import base64
import hashlib
import time

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from app import config as config_module
from app.main import app
from app.ratelimit import sessions
from app.redis_client import get_redis

API_KEY = "test-webhook-key"
API_SECRET = "test-webhook-secret-32-bytes-long"


@pytest.fixture(autouse=True)
def patch_livekit_creds(monkeypatch):
    monkeypatch.setattr(config_module.settings, "livekit_api_key", API_KEY)
    monkeypatch.setattr(config_module.settings, "livekit_api_secret", API_SECRET)


def _sign(body: str, api_key: str = API_KEY, api_secret: str = API_SECRET) -> str:
    body_hash = hashlib.sha256(body.encode()).digest()
    payload = {
        "iss": api_key,
        "sha256": base64.b64encode(body_hash).decode(),
        "exp": int(time.time()) + 60,
    }
    return pyjwt.encode(payload, api_secret, algorithm="HS256")


def _event_body(event: str, room_name: str) -> str:
    return f'{{"event": "{event}", "room": {{"name": "{room_name}"}}}}'


async def _post_webhook(body: str, auth_token: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/webhooks/livekit", content=body, headers={"Authorization": auth_token}
        )


async def test_invalid_signature_rejected():
    body = _event_body("room_started", "tenant-acme-11111111-1111-1111-1111-111111111111")
    resp = await _post_webhook(body, "not-a-real-token")
    assert resp.status_code == 401


async def test_signature_from_wrong_secret_rejected():
    body = _event_body("room_started", "tenant-acme-11111111-1111-1111-1111-111111111111")
    resp = await _post_webhook(body, _sign(body, api_secret="wrong-secret-that-is-32-bytes!!"))
    assert resp.status_code == 401


async def test_room_started_increments_active_count():
    room = "tenant-acme-11111111-1111-1111-1111-111111111111"
    body = _event_body("room_started", room)
    resp = await _post_webhook(body, _sign(body))
    assert resp.status_code == 200

    redis = get_redis()
    assert await sessions.active_count(redis, "acme") == 1


async def test_room_finished_decrements_active_count():
    room = "tenant-acme-11111111-1111-1111-1111-111111111111"
    redis = get_redis()
    await sessions.mark_room_started(redis, "acme", room)
    assert await sessions.active_count(redis, "acme") == 1

    body = _event_body("room_finished", room)
    resp = await _post_webhook(body, _sign(body))
    assert resp.status_code == 200
    assert await sessions.active_count(redis, "acme") == 0


async def test_unparseable_room_name_does_not_crash():
    body = _event_body("room_started", "not-a-tenant-room-name")
    resp = await _post_webhook(body, _sign(body))
    assert resp.status_code == 200
