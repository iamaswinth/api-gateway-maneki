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
