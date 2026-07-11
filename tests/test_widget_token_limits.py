"""POST /widget/token wired to rate limiting (app/ratelimit/limiter.py) and
concurrency (app/ratelimit/sessions.py) — session 2's isolated endpoint
tests (tests/test_widget_token.py) don't cover these; this file does.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app import config as config_module
from app.main import app
from app.ratelimit import sessions
from app.redis_client import get_redis
from app.tenants import store
from app.tenants.models import TenantCreate
from app.widget.tenant_cache import invalidate as invalidate_tenant_cache

ALLOWED_ORIGIN = "https://acme.example.com"


@pytest.fixture(autouse=True)
def patch_livekit_creds(monkeypatch):
    monkeypatch.setattr(config_module.settings, "livekit_api_key", "test-key")
    monkeypatch.setattr(config_module.settings, "livekit_api_secret", "test-secret-32-bytes-long-enough")
    monkeypatch.setattr(config_module.settings, "livekit_url", "wss://example.livekit.cloud")


@pytest.fixture(autouse=True)
def clear_cache():
    yield
    invalidate_tenant_cache("acme")


async def _seed_tenant(max_concurrent_sessions: int = 10) -> None:
    await store.create_tenant(
        "owner-a",
        TenantCreate(
            tenant_id="acme",
            allowed_origin=ALLOWED_ORIGIN,
            max_concurrent_sessions=max_concurrent_sessions,
        ),
    )
    await store.set_published("acme", "owner-a", True)
    invalidate_tenant_cache("acme")


async def _request_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/widget/token", json={"site_id": "acme"}, headers={"Origin": ALLOWED_ORIGIN}
        )


async def test_rate_limit_enforced(monkeypatch):
    monkeypatch.setattr(config_module.settings, "token_rate_limit_per_minute", 2)
    await _seed_tenant()

    assert (await _request_token()).status_code == 200
    assert (await _request_token()).status_code == 200
    resp = await _request_token()
    assert resp.status_code == 429


async def test_concurrent_session_limit_enforced():
    await _seed_tenant(max_concurrent_sessions=1)

    redis = get_redis()
    await sessions.mark_room_started(redis, "acme", "tenant-acme-existing-room")

    resp = await _request_token()
    assert resp.status_code == 429


async def test_token_issuance_does_not_itself_consume_a_concurrency_slot():
    await _seed_tenant(max_concurrent_sessions=1)

    assert (await _request_token()).status_code == 200
    # Issuing a token doesn't call sessions.mark_room_started — only the
    # LiveKit room_started webhook does — so a second request still succeeds
    # until a room actually starts.
    assert (await _request_token()).status_code == 200
