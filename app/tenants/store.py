"""tenant_config storage: schema DDL + CRUD.

Ownership-scoped lookups (`get_owned_tenant`, `update_tenant`, `set_published`)
return None for both "doesn't exist" and "exists but owned by someone else" —
callers must turn that into a 404 either way, so this API can't be used to
enumerate tenant ids a caller doesn't own. `get_tenant` (unscoped) is only for
the widget and internal-service read paths, never behind owner auth.
"""

from typing import Optional

from ..db import get_pool
from .models import TenantConfig, TenantCreate, TenantUpdate

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tenant_config (
    tenant_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    stt_provider TEXT NOT NULL DEFAULT 'deepgram',
    tts_provider TEXT NOT NULL DEFAULT 'cartesia',
    tts_voice_id TEXT,
    llm_tier_default TEXT NOT NULL DEFAULT 'fast',
    greeting JSONB,
    crm_integration JSONB,
    allowed_origin TEXT NOT NULL,
    max_concurrent_sessions INT NOT NULL DEFAULT 10,
    published BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tenant_config_owner_idx ON tenant_config (owner_user_id);
"""

_SELECT_COLUMNS = """
    tenant_id, owner_user_id, stt_provider, tts_provider, tts_voice_id,
    llm_tier_default, greeting, crm_integration, allowed_origin,
    max_concurrent_sessions, published
"""

_schema_ready = False


async def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA_SQL)
    _schema_ready = True


def _row_to_config(row) -> TenantConfig:
    return TenantConfig(**dict(row))


async def create_tenant(owner_user_id: str, data: TenantCreate) -> TenantConfig:
    await ensure_schema()
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""
        INSERT INTO tenant_config
            (tenant_id, owner_user_id, stt_provider, tts_provider, tts_voice_id,
             llm_tier_default, greeting, crm_integration, allowed_origin,
             max_concurrent_sessions)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING {_SELECT_COLUMNS}
        """,
        data.tenant_id,
        owner_user_id,
        data.stt_provider,
        data.tts_provider,
        data.tts_voice_id,
        data.llm_tier_default,
        data.greeting,
        data.crm_integration,
        data.allowed_origin,
        data.max_concurrent_sessions,
    )
    return _row_to_config(row)


async def get_tenant(tenant_id: str) -> Optional[TenantConfig]:
    """Unscoped lookup — for the widget and internal-service read paths only."""
    await ensure_schema()
    pool = await get_pool()
    row = await pool.fetchrow(
        f"SELECT {_SELECT_COLUMNS} FROM tenant_config WHERE tenant_id = $1",
        tenant_id,
    )
    return _row_to_config(row) if row else None


async def get_owned_tenant(tenant_id: str, owner_user_id: str) -> Optional[TenantConfig]:
    await ensure_schema()
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""
        SELECT {_SELECT_COLUMNS} FROM tenant_config
        WHERE tenant_id = $1 AND owner_user_id = $2
        """,
        tenant_id,
        owner_user_id,
    )
    return _row_to_config(row) if row else None


async def list_tenants(owner_user_id: str) -> list[TenantConfig]:
    await ensure_schema()
    pool = await get_pool()
    rows = await pool.fetch(
        f"""
        SELECT {_SELECT_COLUMNS} FROM tenant_config
        WHERE owner_user_id = $1 ORDER BY created_at
        """,
        owner_user_id,
    )
    return [_row_to_config(r) for r in rows]


async def update_tenant(
    tenant_id: str, owner_user_id: str, data: TenantUpdate
) -> Optional[TenantConfig]:
    await ensure_schema()
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return await get_owned_tenant(tenant_id, owner_user_id)
    pool = await get_pool()
    columns = list(fields.keys())
    set_clauses = [f"{col} = ${i + 3}" for i, col in enumerate(columns)]
    set_clauses.append("updated_at = now()")
    query = f"""
        UPDATE tenant_config SET {', '.join(set_clauses)}
        WHERE tenant_id = $1 AND owner_user_id = $2
        RETURNING {_SELECT_COLUMNS}
    """
    row = await pool.fetchrow(query, tenant_id, owner_user_id, *(fields[c] for c in columns))
    return _row_to_config(row) if row else None


async def set_published(
    tenant_id: str, owner_user_id: str, published: bool
) -> Optional[TenantConfig]:
    await ensure_schema()
    pool = await get_pool()
    row = await pool.fetchrow(
        f"""
        UPDATE tenant_config SET published = $3, updated_at = now()
        WHERE tenant_id = $1 AND owner_user_id = $2
        RETURNING {_SELECT_COLUMNS}
        """,
        tenant_id,
        owner_user_id,
        published,
    )
    return _row_to_config(row) if row else None
