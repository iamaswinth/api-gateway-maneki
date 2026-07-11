"""app/ratelimit/limiter.py in isolation, against fakeredis — no real Redis
or HTTP layer needed."""

import pytest
from fakeredis.aioredis import FakeRedis

from app.ratelimit import limiter


@pytest.fixture
async def redis():
    r = FakeRedis()
    yield r
    await r.aclose()


async def test_allows_up_to_limit_then_rejects(redis):
    for _ in range(3):
        assert await limiter.check_and_increment(redis, "acme", limit=3) is True
    assert await limiter.check_and_increment(redis, "acme", limit=3) is False


async def test_different_tenants_have_independent_windows(redis):
    for _ in range(3):
        assert await limiter.check_and_increment(redis, "acme", limit=3) is True
    assert await limiter.check_and_increment(redis, "other-tenant", limit=3) is True


async def test_window_resets_after_expiry(monkeypatch, redis):
    current_time = [1_000_000.0]
    monkeypatch.setattr(limiter.time, "time", lambda: current_time[0])

    for _ in range(3):
        assert await limiter.check_and_increment(redis, "acme", limit=3) is True
    assert await limiter.check_and_increment(redis, "acme", limit=3) is False

    current_time[0] += limiter.WINDOW_SECONDS + 1
    assert await limiter.check_and_increment(redis, "acme", limit=3) is True
