"""Internal, service-token-protected tenant-config read for the voice
runtime. The token check here (app/auth/internal.py) is the *only*
control protecting this endpoint — it's mounted on the same FastAPI app
and port as the public widget/tenant routes (see app/main.py), with no
network-level isolation enforced anywhere in this codebase or its
deployment config. Don't describe or rely on isolation that hasn't
actually been built. What is real: CLAUDE.md's standing rule that no
credential from one trust level (owner JWT, widget token, this internal
token) may satisfy another's check.

Unknown tenant is a 404, not a soft default — preserves the hard-fail
`TenantNotFoundError` semantics `voice_runtime/tenant_config.py` already
relies on.
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth.internal import require_internal_token
from ..tenants import store
from .models import InternalTenantConfig

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/tenant-config/{tenant_id}", response_model=InternalTenantConfig)
async def get_internal_tenant_config(
    tenant_id: str, _: None = Depends(require_internal_token)
) -> InternalTenantConfig:
    tenant = await store.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return InternalTenantConfig(
        tenant_id=tenant.tenant_id,
        stt_provider=tenant.stt_provider,
        tts_provider=tenant.tts_provider,
        tts_voice_id=tenant.tts_voice_id,
        llm_tier_default=tenant.llm_tier_default,
        allowed_origin=tenant.allowed_origin,
        max_concurrent_sessions=tenant.max_concurrent_sessions,
        published=tenant.published,
        greeting=tenant.greeting,
    )
