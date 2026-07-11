"""Owner-facing tenant CRUD: cross-owner isolation is the critical property
here (see CLAUDE.md's standing rule about trust-level separation). Auth is
exercised via FastAPI dependency overrides here — app/auth/clerk.py itself is
covered independently in test_clerk_auth.py.

Uses an ASGI-transport httpx.AsyncClient (not starlette's TestClient) so
requests run on the same event loop as the test — TestClient drives the app
from a separate thread/loop, which fights with the asyncpg pool that this
test's fixtures already bound to the current loop.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.clerk import OwnerIdentity, require_owner
from app.main import app


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def client_as(owner_user_id: str) -> AsyncClient:
    app.dependency_overrides[require_owner] = lambda: OwnerIdentity(user_id=owner_user_id)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _tenant_payload(tenant_id="acme"):
    return {
        "tenant_id": tenant_id,
        "allowed_origin": "https://acme.example.com",
        "max_concurrent_sessions": 5,
    }


async def test_create_and_get_own_tenant():
    async with client_as("owner-a") as client:
        resp = await client.post("/tenants", json=_tenant_payload())
        assert resp.status_code == 201
        body = resp.json()
        assert body["tenant_id"] == "acme"
        assert body["owner_user_id"] == "owner-a"
        assert body["published"] is False

        resp = await client.get("/tenants/acme")
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "acme"


async def test_duplicate_tenant_id_rejected():
    async with client_as("owner-a") as client:
        await client.post("/tenants", json=_tenant_payload())
        resp = await client.post("/tenants", json=_tenant_payload())
        assert resp.status_code == 409


async def test_cross_owner_cannot_read():
    async with client_as("owner-a") as client:
        await client.post("/tenants", json=_tenant_payload())
    async with client_as("owner-b") as client:
        resp = await client.get("/tenants/acme")
        assert resp.status_code == 404


async def test_cross_owner_cannot_update():
    async with client_as("owner-a") as client:
        await client.post("/tenants", json=_tenant_payload())
    async with client_as("owner-b") as client:
        resp = await client.patch(
            "/tenants/acme", json={"allowed_origin": "https://evil.example.com"}
        )
        assert resp.status_code == 404

    async with client_as("owner-a") as client:
        resp = await client.get("/tenants/acme")
        assert resp.json()["allowed_origin"] == "https://acme.example.com"


async def test_cross_owner_cannot_publish():
    async with client_as("owner-a") as client:
        await client.post("/tenants", json=_tenant_payload())
    async with client_as("owner-b") as client:
        resp = await client.post("/tenants/acme/publish")
        assert resp.status_code == 404

    async with client_as("owner-a") as client:
        resp = await client.get("/tenants/acme")
        assert resp.json()["published"] is False


async def test_owner_can_publish_and_unpublish_own_tenant():
    async with client_as("owner-a") as client:
        await client.post("/tenants", json=_tenant_payload())

        resp = await client.post("/tenants/acme/publish")
        assert resp.status_code == 200
        assert resp.json()["published"] is True

        resp = await client.post("/tenants/acme/unpublish")
        assert resp.status_code == 200
        assert resp.json()["published"] is False


async def test_list_only_returns_owned_tenants():
    async with client_as("owner-a") as client:
        await client.post("/tenants", json=_tenant_payload("acme-a"))
    async with client_as("owner-b") as client:
        await client.post("/tenants", json=_tenant_payload("acme-b"))

    async with client_as("owner-a") as client:
        resp = await client.get("/tenants")
        assert resp.status_code == 200
        tenant_ids = {t["tenant_id"] for t in resp.json()}
        assert tenant_ids == {"acme-a"}


async def test_get_unknown_tenant_returns_404():
    async with client_as("owner-a") as client:
        resp = await client.get("/tenants/does-not-exist")
        assert resp.status_code == 404


async def test_unauthenticated_request_rejected():
    app.dependency_overrides.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/tenants")
        assert resp.status_code == 401
