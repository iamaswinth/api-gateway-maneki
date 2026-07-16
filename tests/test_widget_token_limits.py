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
async def clear_cache():
    yield
    await invalidate_tenant_cache("acme")


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
    await invalidate_tenant_cache("acme")


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


async def test_ip_limit_throttles_flood_of_never_repeated_site_ids(monkeypatch):
    # The vulnerability this closes: a site_id-keyed limiter does nothing
    # against a flood that never repeats a site_id (every request gets a
    # fresh, empty bucket), and get_cached_tenant does a real DB query on
    # every miss. Confirm the *global per-IP* check throttles this even
    # though not one of these site_ids is ever reused, and even though none
    # of them belong to a real tenant (so the per-site_id check further down
    # is never even reached).
    monkeypatch.setattr(config_module.settings, "widget_token_ip_rate_limit_per_minute", 5)

    statuses = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for i in range(8):
            resp = await client.post(
                "/widget/token",
                json={"site_id": f"never-repeated-{i}"},
                headers={"Origin": ALLOWED_ORIGIN},
            )
            statuses.append(resp.status_code)

    # First 5 pass the IP gate and fall through to "unknown tenant" (403);
    # the rest never even get that far.
    assert statuses[:5] == [403] * 5
    assert statuses[5:] == [429] * 3
