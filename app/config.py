from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="GATEWAY_", extra="ignore")

    # Postgres, same instance as the other Maneki services in dev, own schema
    # (mirrors voice_runtime's `voice` schema isolation pattern).
    database_url: str = "postgresql://postgres:postgres@localhost:5433/postgres"
    db_schema: str = "gateway"

    # Redis: new to this stack. Backs rate-limit windows and active-session counts.
    redis_url: str = "redis://localhost:6379/0"

    # Clerk owner auth. JWKS fetched from {clerk_issuer}/.well-known/jwks.json
    # and cached in-process.
    clerk_issuer: str = ""
    clerk_jwks_cache_seconds: int = 3600

    # Service-to-service token for the voice runtime's internal endpoint.
    # Distinct trust level from Clerk JWTs and widget tokens — never accepted
    # interchangeably (see CLAUDE.md standing instruction).
    internal_token: str = ""

    # LiveKit: mints widget tokens, verifies webhook signatures.
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Ingestion service, for authenticated forwarding (app/forward/).
    ingestion_base_url: str = "http://localhost:8000"
    ingestion_timeout_seconds: float = 10.0
    # Shared service-to-service secret ingestion requires from any internal
    # caller (this gateway and the voice runtime both present it) — locks
    # ingestion's otherwise-unauthenticated endpoints to sanctioned callers.
    ingestion_internal_token: str = ""

    # Widget token issuance.
    token_rate_limit_per_minute: int = 30
    tenant_config_cache_seconds: int = 60
    widget_token_ttl_seconds: int = 600

    # Active-session TTL guard: caps how long a room can hold a concurrency
    # slot if a LiveKit room_finished webhook is ever missed.
    active_session_ttl_seconds: int = 7200


settings = Settings()
