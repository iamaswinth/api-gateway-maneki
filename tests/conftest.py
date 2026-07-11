import pytest
from fakeredis.aioredis import FakeRedis

from app import redis_client as redis_client_module
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


@pytest.fixture(autouse=True)
async def fake_redis():
    # get_redis() is a module-level singleton pointed at a real Redis by
    # default — swap it for a fresh fakeredis instance for every test so
    # nothing here needs a live Redis server.
    fake = FakeRedis(decode_responses=True)
    redis_client_module._client = fake
    yield fake
    await fake.aclose()
    redis_client_module._client = None
