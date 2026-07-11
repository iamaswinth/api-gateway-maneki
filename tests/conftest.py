import pytest

from app.db import close_pool, get_pool
from app.tenants import store


@pytest.fixture(autouse=True)
async def clean_tenant_config():
    # pytest-asyncio gives each test function its own event loop, but the
    # asyncpg pool is a module-level singleton bound to whichever loop
    # created it — so it must be torn down and rebuilt fresh every test.
    await close_pool()
    store._schema_ready = False
    await store.ensure_schema()
    pool = await get_pool()
    await pool.execute("TRUNCATE TABLE tenant_config")
    yield
    await close_pool()
