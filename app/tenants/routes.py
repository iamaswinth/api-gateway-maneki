"""Owner-facing tenant_config CRUD, behind Clerk JWT auth + ownership checks."""

from fastapi import APIRouter, Depends, HTTPException

from ..auth.clerk import OwnerIdentity, require_owner
from ..widget.tenant_cache import invalidate as invalidate_tenant_cache
from . import store
from .models import TenantConfig, TenantCreate, TenantUpdate

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=TenantConfig, status_code=201)
async def create(
    data: TenantCreate, owner: OwnerIdentity = Depends(require_owner)
) -> TenantConfig:
    existing = await store.get_tenant(data.tenant_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="tenant_id already exists")
    return await store.create_tenant(owner.user_id, data)


@router.get("", response_model=list[TenantConfig])
async def list_mine(owner: OwnerIdentity = Depends(require_owner)) -> list[TenantConfig]:
    return await store.list_tenants(owner.user_id)


@router.get("/{tenant_id}", response_model=TenantConfig)
async def get(tenant_id: str, owner: OwnerIdentity = Depends(require_owner)) -> TenantConfig:
    tenant = await store.get_owned_tenant(tenant_id, owner.user_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch("/{tenant_id}", response_model=TenantConfig)
async def update(
    tenant_id: str, data: TenantUpdate, owner: OwnerIdentity = Depends(require_owner)
) -> TenantConfig:
    tenant = await store.update_tenant(tenant_id, owner.user_id, data)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    invalidate_tenant_cache(tenant_id)
    return tenant


@router.post("/{tenant_id}/publish", response_model=TenantConfig)
async def publish(
    tenant_id: str, owner: OwnerIdentity = Depends(require_owner)
) -> TenantConfig:
    tenant = await store.set_published(tenant_id, owner.user_id, True)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    invalidate_tenant_cache(tenant_id)
    return tenant


@router.post("/{tenant_id}/unpublish", response_model=TenantConfig)
async def unpublish(
    tenant_id: str, owner: OwnerIdentity = Depends(require_owner)
) -> TenantConfig:
    tenant = await store.set_published(tenant_id, owner.user_id, False)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    invalidate_tenant_cache(tenant_id)
    return tenant
