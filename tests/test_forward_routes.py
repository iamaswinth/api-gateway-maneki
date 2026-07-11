"""Authenticated forwarding to the ingestion service: ownership must be
verified before any outbound call, and tenant_id is always server-injected
— never taken from the caller's request body. Ingestion itself is mocked
via respx; no live service needed.
"""

import json

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response

from app import config as config_module
from app.auth.clerk import OwnerIdentity, require_owner
from app.main import app
from app.tenants import store
from app.tenants.models import TenantCreate

INGESTION_BASE = "http://ingestion.test"


@pytest.fixture(autouse=True)
def patch_ingestion_base(monkeypatch):
    monkeypatch.setattr(config_module.settings, "ingestion_base_url", INGESTION_BASE)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def client_as(owner_user_id: str) -> AsyncClient:
    app.dependency_overrides[require_owner] = lambda: OwnerIdentity(user_id=owner_user_id)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_tenant(tenant_id="acme", owner_user_id="owner-a"):
    await store.create_tenant(
        owner_user_id,
        TenantCreate(tenant_id=tenant_id, allowed_origin="https://acme.example.com"),
    )


@respx.mock
async def test_scrape_forward_injects_tenant_id_and_ignores_spoofed_one():
    await _seed_tenant()
    route = respx.post(f"{INGESTION_BASE}/scrape").mock(
        return_value=Response(
            202,
            json={
                "job_id": "job-1",
                "url": "https://acme.example.com",
                "tenant_id": "acme",
                "status": "scraping",
            },
        )
    )
    async with client_as("owner-a") as client:
        resp = await client.post(
            "/forward/scrape/acme",
            json={"url": "https://acme.example.com", "tenant_id": "someone-else"},
        )
    assert resp.status_code == 202
    assert route.called
    forwarded = json.loads(route.calls[0].request.content)
    assert forwarded["tenant_id"] == "acme"


@respx.mock
async def test_scrape_forward_rejects_non_owner_before_any_outbound_call():
    await _seed_tenant()
    route = respx.post(f"{INGESTION_BASE}/scrape").mock(return_value=Response(202, json={}))
    async with client_as("owner-b") as client:
        resp = await client.post("/forward/scrape/acme", json={"url": "https://acme.example.com"})
    assert resp.status_code == 404
    assert not route.called


@respx.mock
async def test_get_job_rejects_non_owner_before_any_outbound_call():
    await _seed_tenant()
    route = respx.get(f"{INGESTION_BASE}/scrape/job-1").mock(return_value=Response(200, json={}))
    async with client_as("owner-b") as client:
        resp = await client.get("/forward/scrape/acme/job-1")
    assert resp.status_code == 404
    assert not route.called


@respx.mock
async def test_get_job_rejects_job_belonging_to_different_tenant():
    await _seed_tenant()
    respx.get(f"{INGESTION_BASE}/scrape/job-1").mock(
        return_value=Response(
            200,
            json={"job_id": "job-1", "tenant_id": "other-tenant", "url": "x", "status": "completed"},
        )
    )
    async with client_as("owner-a") as client:
        resp = await client.get("/forward/scrape/acme/job-1")
    assert resp.status_code == 404


@respx.mock
async def test_generate_sales_script_resolves_job_tenant_before_forwarding():
    await _seed_tenant()
    respx.get(f"{INGESTION_BASE}/scrape/job-1").mock(
        return_value=Response(
            200,
            json={
                "job_id": "job-1",
                "tenant_id": "acme",
                "url": "x",
                "status": "completed",
                "persisted": True,
            },
        )
    )
    generate_route = respx.post(f"{INGESTION_BASE}/sales-script/job-1").mock(
        return_value=Response(
            202, json={"tenant_id": "acme", "site_url": "x", "job_id": "job-1", "status": "generating"}
        )
    )
    async with client_as("owner-a") as client:
        resp = await client.post("/forward/sales-script/generate/acme/job-1")
    assert resp.status_code == 202
    assert generate_route.called


@respx.mock
async def test_generate_sales_script_rejects_job_from_different_tenant_without_forwarding():
    await _seed_tenant()
    respx.get(f"{INGESTION_BASE}/scrape/job-1").mock(
        return_value=Response(
            200,
            json={"job_id": "job-1", "tenant_id": "other-tenant", "url": "x", "status": "completed"},
        )
    )
    generate_route = respx.post(f"{INGESTION_BASE}/sales-script/job-1").mock(
        return_value=Response(202, json={})
    )
    async with client_as("owner-a") as client:
        resp = await client.post("/forward/sales-script/generate/acme/job-1")
    assert resp.status_code == 404
    assert not generate_route.called


@respx.mock
async def test_get_sales_script_forwards_with_site_url_param():
    await _seed_tenant()
    route = respx.get(
        f"{INGESTION_BASE}/sales-script/acme", params={"site_url": "https://acme.example.com"}
    ).mock(
        return_value=Response(
            200,
            json={
                "tenant_id": "acme",
                "site_url": "https://acme.example.com",
                "job_id": "job-1",
                "status": "ready",
            },
        )
    )
    async with client_as("owner-a") as client:
        resp = await client.get(
            "/forward/sales-script/acme", params={"site_url": "https://acme.example.com"}
        )
    assert resp.status_code == 200
    assert route.called


@respx.mock
async def test_approve_sales_script_rejects_non_owner_before_any_outbound_call():
    await _seed_tenant()
    route = respx.post(f"{INGESTION_BASE}/sales-script/acme/approve").mock(
        return_value=Response(200, json={})
    )
    async with client_as("owner-b") as client:
        resp = await client.post("/forward/sales-script/acme/approve")
    assert resp.status_code == 404
    assert not route.called


@respx.mock
async def test_approve_sales_script_forwards_for_owner():
    await _seed_tenant()
    route = respx.post(f"{INGESTION_BASE}/sales-script/acme/approve").mock(
        return_value=Response(
            200, json={"tenant_id": "acme", "site_url": "x", "status": "ready", "indexed_chunks": 5}
        )
    )
    async with client_as("owner-a") as client:
        resp = await client.post("/forward/sales-script/acme/approve")
    assert resp.status_code == 200
    assert route.called
