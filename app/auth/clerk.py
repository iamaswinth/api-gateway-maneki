"""Clerk JWT verification for owner-facing endpoints.

Fetches Clerk's JWKS and caches it in-process (TTL: settings.clerk_jwks_cache_seconds).
Verifies RS256 signature, issuer, and expiry; extracts the Clerk user id from
the `sub` claim as `OwnerIdentity`.

This is a distinct trust level from the widget flow (app/widget/) and the
internal service token (app/auth/internal.py) — never share a validation code
path with those, and never accept an internal or widget credential here.
"""

import time
from dataclasses import dataclass
from typing import Optional

import httpx
import jwt
from fastapi import Header, HTTPException
from jwt import PyJWK

from ..config import settings

_jwks_cache: dict[str, PyJWK] = {}
_jwks_fetched_at: float = 0.0


@dataclass(frozen=True)
class OwnerIdentity:
    user_id: str


async def _fetch_jwks() -> dict[str, PyJWK]:
    jwks_url = f"{settings.clerk_issuer.rstrip('/')}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(jwks_url)
        resp.raise_for_status()
    data = resp.json()
    return {jwk_dict["kid"]: PyJWK.from_dict(jwk_dict) for jwk_dict in data["keys"]}


async def _get_signing_key(kid: str) -> PyJWK:
    global _jwks_cache, _jwks_fetched_at
    now = time.monotonic()
    if not _jwks_cache or (now - _jwks_fetched_at) > settings.clerk_jwks_cache_seconds:
        _jwks_cache = await _fetch_jwks()
        _jwks_fetched_at = now
    key = _jwks_cache.get(kid)
    if key is None:
        # kid rotated since our cache — refresh once before giving up.
        _jwks_cache = await _fetch_jwks()
        _jwks_fetched_at = now
        key = _jwks_cache.get(kid)
    if key is None:
        raise HTTPException(status_code=401, detail="Unknown signing key")
    return key


async def require_owner(authorization: Optional[str] = Header(default=None)) -> OwnerIdentity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[len("Bearer "):]
    try:
        unverified = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Malformed token")
    kid = unverified.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Malformed token")

    signing_key = await _get_signing_key(kid)
    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={"require": ["sub", "exp"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
    return OwnerIdentity(user_id=claims["sub"])
