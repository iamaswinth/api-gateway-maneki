"""Verifies app/auth/clerk.py in isolation: real RS256 signing/verification
against a locally-generated keypair, with `_fetch_jwks` monkeypatched so no
network call to Clerk is made.
"""

import json
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from app import config as config_module
from app.auth import clerk

TEST_ISSUER = "https://test.clerk.accounts.dev"
TEST_KID = "test-kid-1"


def _private_key_pem(private_key) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _make_token(private_key, kid=TEST_KID, sub="user_abc", issuer=TEST_ISSUER, exp_delta=3600):
    payload = {"sub": sub, "iss": issuer, "exp": int(time.time()) + exp_delta}
    return pyjwt.encode(payload, _private_key_pem(private_key), algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def rsa_keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def patch_clerk(monkeypatch, rsa_keypair):
    jwk_json = RSAAlgorithm.to_jwk(rsa_keypair.public_key())
    jwk_dict = json.loads(jwk_json)
    jwk_dict.update(kid=TEST_KID, use="sig", alg="RS256")

    async def fake_fetch_jwks():
        return {TEST_KID: PyJWK.from_dict(jwk_dict)}

    monkeypatch.setattr(clerk, "_fetch_jwks", fake_fetch_jwks)
    monkeypatch.setattr(clerk, "_jwks_cache", {})
    monkeypatch.setattr(clerk, "_jwks_fetched_at", 0.0)
    monkeypatch.setattr(config_module.settings, "clerk_issuer", TEST_ISSUER)


async def test_valid_token_returns_owner_identity(rsa_keypair):
    token = _make_token(rsa_keypair, sub="user_xyz")
    identity = await clerk.require_owner(authorization=f"Bearer {token}")
    assert identity.user_id == "user_xyz"


async def test_missing_header_rejected():
    with pytest.raises(HTTPException) as exc:
        await clerk.require_owner(authorization=None)
    assert exc.value.status_code == 401


async def test_non_bearer_header_rejected():
    with pytest.raises(HTTPException) as exc:
        await clerk.require_owner(authorization="Basic abc123")
    assert exc.value.status_code == 401


async def test_wrong_issuer_rejected(rsa_keypair):
    token = _make_token(rsa_keypair, issuer="https://evil.example.com")
    with pytest.raises(HTTPException) as exc:
        await clerk.require_owner(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


async def test_expired_token_rejected(rsa_keypair):
    token = _make_token(rsa_keypair, exp_delta=-10)
    with pytest.raises(HTTPException) as exc:
        await clerk.require_owner(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


async def test_token_signed_by_unknown_key_rejected(rsa_keypair):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    # Claims the known kid but is actually signed by a different private key.
    token = _make_token(other_key, kid=TEST_KID)
    with pytest.raises(HTTPException) as exc:
        await clerk.require_owner(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


async def test_missing_kid_rejected(rsa_keypair):
    payload = {"sub": "user_abc", "iss": TEST_ISSUER, "exp": int(time.time()) + 3600}
    token = pyjwt.encode(payload, _private_key_pem(rsa_keypair), algorithm="RS256")
    with pytest.raises(HTTPException) as exc:
        await clerk.require_owner(authorization=f"Bearer {token}")
    assert exc.value.status_code == 401
