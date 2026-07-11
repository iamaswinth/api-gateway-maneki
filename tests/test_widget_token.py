"""POST /widget/token: the actual tenant-isolation security boundary. No
rate limiting is wired in yet (app/ratelimit/, added separately) — these
tests cover origin/published gating and the token contents only.
"""

import json

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from app import config as config_module
from app.main import app
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


async def _make_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_tenant(published: bool, allowed_origin: str = ALLOWED_ORIGIN) -> None:
    tenant = await store.create_tenant(
        "owner-a",
        TenantCreate(tenant_id="acme", allowed_origin=allowed_origin, max_concurrent_sessions=5),
    )
    if published:
        await store.set_published("acme", "owner-a", True)
    invalidate_tenant_cache("acme")


async def test_unpublished_tenant_rejected():
    await _seed_tenant(published=False)
    async with await _make_client() as client:
        resp = await client.post(
            "/widget/token", json={"site_id": "acme"}, headers={"Origin": ALLOWED_ORIGIN}
        )
    assert resp.status_code == 403


async def test_unknown_tenant_rejected():
    async with await _make_client() as client:
        resp = await client.post(
            "/widget/token", json={"site_id": "does-not-exist"}, headers={"Origin": ALLOWED_ORIGIN}
        )
    assert resp.status_code == 403


async def test_origin_mismatch_rejected():
    await _seed_tenant(published=True)
    async with await _make_client() as client:
        resp = await client.post(
            "/widget/token", json={"site_id": "acme"}, headers={"Origin": "https://evil.example.com"}
        )
    assert resp.status_code == 403


async def test_missing_origin_header_rejected():
    await _seed_tenant(published=True)
    async with await _make_client() as client:
        resp = await client.post("/widget/token", json={"site_id": "acme"})
    assert resp.status_code == 403


async def test_valid_request_returns_well_formed_token():
    await _seed_tenant(published=True)
    async with await _make_client() as client:
        resp = await client.post(
            "/widget/token",
            json={"site_id": "acme", "page_url": "https://acme.example.com/pricing"},
            headers={"Origin": ALLOWED_ORIGIN},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["livekit_url"] == "wss://example.livekit.cloud"
    assert body["room"].startswith("tenant-acme-")

    claims = pyjwt.decode(
        body["token"], config_module.settings.livekit_api_secret, algorithms=["HS256"]
    )
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["room"] == body["room"]

    dispatch = claims["roomConfig"]["agents"][0]
    assert dispatch["agentName"] == "voice-runtime"
    metadata = json.loads(dispatch["metadata"])
    assert metadata["tenant_id"] == "acme"
    assert metadata["page_url"] == "https://acme.example.com/pricing"
    assert "visitor_id" in metadata


async def test_session_id_passed_through_to_dispatch_metadata():
    # Widget-supplied session_id becomes the voice runtime's thread_id, so a
    # returning visitor (same sessionStorage session_id, new page/room)
    # resumes the same conversation instead of starting fresh.
    await _seed_tenant(published=True)
    async with await _make_client() as client:
        resp = await client.post(
            "/widget/token",
            json={"site_id": "acme", "session_id": "sess-abc-123"},
            headers={"Origin": ALLOWED_ORIGIN},
        )
    assert resp.status_code == 200
    claims = pyjwt.decode(
        resp.json()["token"], config_module.settings.livekit_api_secret, algorithms=["HS256"]
    )
    metadata = json.loads(claims["roomConfig"]["agents"][0]["metadata"])
    assert metadata["session_id"] == "sess-abc-123"


async def test_missing_session_id_omitted_from_dispatch_metadata():
    await _seed_tenant(published=True)
    async with await _make_client() as client:
        resp = await client.post(
            "/widget/token", json={"site_id": "acme"}, headers={"Origin": ALLOWED_ORIGIN}
        )
    claims = pyjwt.decode(
        resp.json()["token"], config_module.settings.livekit_api_secret, algorithms=["HS256"]
    )
    metadata = json.loads(claims["roomConfig"]["agents"][0]["metadata"])
    assert "session_id" not in metadata


async def test_cors_preflight_allows_arbitrary_origin():
    # The per-tenant Origin check happens inside the handler (needs the
    # request body's site_id, which a preflight never carries) — CORS itself
    # must stay permissive so the browser lets the actual POST through to
    # reach that check at all.
    async with await _make_client() as client:
        resp = await client.options(
            "/widget/token",
            headers={
                "Origin": "https://some-owners-site.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert resp.status_code == 200
    # Literal "*", not origin-reflection — correct and sufficient since the
    # widget's fetch never sends credentials (no cookie-based auth exists
    # anywhere in this service).
    assert resp.headers["access-control-allow-origin"] == "*"
