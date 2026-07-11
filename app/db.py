"""Shared asyncpg connection pool, scoped to the gateway's own Postgres schema.

Same instance as the ingestion service and voice runtime in dev, but the
gateway never reads or writes their tables — only `db_schema` (default
`gateway`), mirroring voice_runtime's `voice`-schema isolation.
"""

import json
from typing import Optional
from urllib.parse import quote

import asyncpg

from .config import settings

_pool: Optional[asyncpg.Pool] = None


def _dsn_with_schema() -> str:
    separator = "&" if "?" in settings.database_url else "?"
    options = quote(f"-c search_path={settings.db_schema}", safe="")
    return f"{settings.database_url}{separator}options={options}"


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {settings.db_schema}")
    # Transparent jsonb <-> Python dict roundtrip (greeting, crm_integration),
    # same pattern as the ingestion service's app/db.py.
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            _dsn_with_schema(), init=_init_connection, min_size=1, max_size=5
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
