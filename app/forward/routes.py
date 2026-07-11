"""Authenticated proxies to the ingestion service's owner-facing endpoints.

The ingestion service (Firecrawl-scraper-ingestion) has no auth of its own —
every endpoint trusts whatever tenant_id the caller passes. This router is
what stops an arbitrary caller who knows a tenant_id from triggering scrapes
or approving sales scripts: ownership against `tenant_config` is checked
*before* any outbound call, and `tenant_id` is always server-injected into
forwarded bodies/paths, never taken from the request.
"""

from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ..auth.clerk import OwnerIdentity, require_owner
from ..tenants import store as tenant_store
from . import client
from .models import ScrapeForwardRequest

router = APIRouter(prefix="/forward", tags=["forward"])


async def _require_owned_tenant(tenant_id: str, owner: OwnerIdentity) -> None:
    tenant = await tenant_store.get_owned_tenant(tenant_id, owner.user_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")


def _passthrough(resp: httpx.Response) -> JSONResponse:
    return JSONResponse(status_code=resp.status_code, content=resp.json())


@router.post("/scrape/{tenant_id}")
async def forward_scrape(
    tenant_id: str, data: ScrapeForwardRequest, owner: OwnerIdentity = Depends(require_owner)
) -> JSONResponse:
    await _require_owned_tenant(tenant_id, owner)
    body = data.model_dump(mode="json", exclude_none=True)
    body["tenant_id"] = tenant_id
    resp = await client.post("/scrape", json=body)
    return _passthrough(resp)


@router.get("/scrape/{tenant_id}/{job_id}")
async def forward_get_job(
    tenant_id: str, job_id: str, owner: OwnerIdentity = Depends(require_owner)
) -> JSONResponse:
    await _require_owned_tenant(tenant_id, owner)
    resp = await client.get(f"/scrape/{job_id}")
    if resp.status_code == 200 and resp.json().get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="Job not found for this tenant")
    return _passthrough(resp)


@router.post("/sales-script/generate/{tenant_id}/{job_id}")
async def forward_generate_sales_script(
    tenant_id: str, job_id: str, owner: OwnerIdentity = Depends(require_owner)
) -> JSONResponse:
    await _require_owned_tenant(tenant_id, owner)

    # Ingestion's generate endpoint is keyed by job_id, not tenant_id — resolve
    # the job first and confirm it actually belongs to this tenant before
    # forwarding, since /sales-script/{job_id} would otherwise let an owner
    # trigger generation for a job that isn't theirs just by guessing a job_id.
    job_resp = await client.get(f"/scrape/{job_id}")
    if job_resp.status_code != 200 or job_resp.json().get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="Job not found for this tenant")

    resp = await client.post(f"/sales-script/{job_id}")
    return _passthrough(resp)


@router.get("/sales-script/{tenant_id}")
async def forward_get_sales_script(
    tenant_id: str,
    site_url: Optional[str] = Query(default=None),
    owner: OwnerIdentity = Depends(require_owner),
) -> JSONResponse:
    await _require_owned_tenant(tenant_id, owner)
    params = {"site_url": site_url} if site_url else None
    resp = await client.get(f"/sales-script/{tenant_id}", params=params)
    return _passthrough(resp)


@router.post("/sales-script/{tenant_id}/approve")
async def forward_approve_sales_script(
    tenant_id: str,
    site_url: Optional[str] = Query(default=None),
    owner: OwnerIdentity = Depends(require_owner),
) -> JSONResponse:
    await _require_owned_tenant(tenant_id, owner)
    params = {"site_url": site_url} if site_url else None
    resp = await client.post(f"/sales-script/{tenant_id}/approve", params=params)
    return _passthrough(resp)
