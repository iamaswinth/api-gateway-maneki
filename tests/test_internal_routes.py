"""GET /internal/tenant-config/{tenant_id}: the third trust level. Must
reject missing/wrong tokens, must reject a valid Clerk JWT (cross-trust-level
credential), and the internal token itself must be rejected on owner routes
— see CLAUDE.md's standing rule that no credential from one trust level may
satisfy another's check.
"""

import json
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from app import config as config_module
from app.auth import clerk
from app.main import app
from app.tenants import store
from app.tenants.models import TenantCreate

INTERNAL_TOKEN = "test-internal-token"
CLERK_ISSUER = "https://test.clerk.accounts.dev"
CLERK_KID = "test-kid"


@pytest.fixture(autouse=True)
def patch_internal_token(monkeypatch):
    monkeypatch.setattr(config_module.settings, "internal_token", INTERNAL_TOKEN)


@pytest.fixture
def rsa_keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def clerk_jwt(monkeypatch, rsa_keypair):
    jwk_json = RSAAlgorithm.to_jwk(rsa_keypair.public_key())
    jwk_dict = json.loads(jwk_json)
    jwk_dict.update(kid=CLERK_KID, use="sig", alg="RS256")

    async def fake_fetch_jwks():
        return {CLERK_KID: PyJWK.from_dict(jwk_dict)}

    monkeypatch.setattr(clerk, "_fetch_jwks", fake_fetch_jwks)
    monkeypatch.setattr(clerk, "_jwks_cache", {})
    monkeypatch.setattr(clerk, "_jwks_fetched_at", 0.0)
    monkeypatch.setattr(config_module.settings, "clerk_issuer", CLERK_ISSUER)

    private_pem = rsa_keypair.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    payload = {"sub": "user_abc", "iss": CLERK_ISSUER, "exp": int(time.time()) + 3600}
    return pyjwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": CLERK_KID})


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_tenant():
    await store.create_tenant(
        "owner-a",
        TenantCreate(
            tenant_id="acme",
            allowed_origin="http://localhost:5173",
            tts_voice_id="voice-1",
            greeting={"new": "hi", "returning": "welcome back"},
        ),
    )
    await store.set_published("acme", "owner-a", True)


async def test_missing_token_rejected():
    async with await _client() as client:
        resp = await client.get("/internal/tenant-config/acme")
    assert resp.status_code == 401


async def test_wrong_token_rejected():
    async with await _client() as client:
        resp = await client.get(
            "/internal/tenant-config/acme", headers={"Authorization": "Bearer wrong-token"}
        )
    assert resp.status_code == 401


async def test_clerk_jwt_rejected_here(clerk_jwt):
    async with await _client() as client:
        resp = await client.get(
            "/internal/tenant-config/acme", headers={"Authorization": f"Bearer {clerk_jwt}"}
        )
    assert resp.status_code == 401


async def test_internal_token_rejected_on_owner_route():
    async with await _client() as client:
        resp = await client.get(
            "/tenants", headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"}
        )
    assert resp.status_code == 401


async def test_unknown_tenant_returns_404_not_default():
    async with await _client() as client:
        resp = await client.get(
            "/internal/tenant-config/does-not-exist",
            headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
        )
    assert resp.status_code == 404


async def test_valid_request_matches_fixture_shape():
    await _seed_tenant()
    async with await _client() as client:
        resp = await client.get(
            "/internal/tenant-config/acme", headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "tenant_id",
        "stt_provider",
        "tts_provider",
        "tts_voice_id",
        "llm_tier_default",
        "allowed_origin",
        "max_concurrent_sessions",
        "published",
        "greeting",
    }
    assert body["tenant_id"] == "acme"
    assert body["published"] is True
    assert body["greeting"] == {"new": "hi", "returning": "welcome back"}
