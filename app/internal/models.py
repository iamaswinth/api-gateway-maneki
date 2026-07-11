"""Response shape for GET /internal/tenant-config/{tenant_id}.

Must match voice_runtime/fixtures/tenant_config.json exactly — that fixture
is the drop-in contract `voice_runtime/tenant_config.py::load_tenant_config`
expects to swap to once this endpoint exists. Deliberately excludes
owner_user_id and crm_integration, which are gateway-internal, not part of
the runtime's contract.
"""

from typing import Optional

from pydantic import BaseModel


class InternalTenantConfig(BaseModel):
    tenant_id: str
    stt_provider: str
    tts_provider: str
    tts_voice_id: Optional[str] = None
    llm_tier_default: str
    allowed_origin: str
    max_concurrent_sessions: int
    published: bool
    greeting: Optional[dict] = None
