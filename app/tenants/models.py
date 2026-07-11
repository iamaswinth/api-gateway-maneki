from typing import Optional

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    allowed_origin: str = Field(min_length=1)
    stt_provider: str = "deepgram"
    tts_provider: str = "cartesia"
    tts_voice_id: Optional[str] = None
    llm_tier_default: str = "fast"
    greeting: Optional[dict] = None
    crm_integration: Optional[dict] = None
    max_concurrent_sessions: int = 10


class TenantUpdate(BaseModel):
    allowed_origin: Optional[str] = None
    stt_provider: Optional[str] = None
    tts_provider: Optional[str] = None
    tts_voice_id: Optional[str] = None
    llm_tier_default: Optional[str] = None
    greeting: Optional[dict] = None
    crm_integration: Optional[dict] = None
    max_concurrent_sessions: Optional[int] = None


class TenantConfig(BaseModel):
    tenant_id: str
    owner_user_id: str
    stt_provider: str
    tts_provider: str
    tts_voice_id: Optional[str] = None
    llm_tier_default: str
    greeting: Optional[dict] = None
    crm_integration: Optional[dict] = None
    allowed_origin: str
    max_concurrent_sessions: int
    published: bool
