"""app/ratelimit/sessions.py in isolation, against fakeredis."""

import asyncio

import pytest
from fakeredis.aioredis import FakeRedis

from app import config as config_module
from app.ratelimit import sessions


@pytest.fixture
async def redis():
    r = FakeRedis()
    yield r
    await r.aclose()


async def test_count_increments_and_decrements(redis):
    assert await sessions.active_count(redis, "acme") == 0

    await sessions.mark_room_started(redis, "acme", "tenant-acme-room1")
    await sessions.mark_room_started(redis, "acme", "tenant-acme-room2")
    assert await sessions.active_count(redis, "acme") == 2

    await sessions.mark_room_finished(redis, "acme", "tenant-acme-room1")
    assert await sessions.active_count(redis, "acme") == 1


async def test_duplicate_room_started_is_idempotent(redis):
    await sessions.mark_room_started(redis, "acme", "room1")
    await sessions.mark_room_started(redis, "acme", "room1")
    assert await sessions.active_count(redis, "acme") == 1


async def test_room_finished_on_unknown_room_is_noop(redis):
    await sessions.mark_room_finished(redis, "acme", "does-not-exist")
    assert await sessions.active_count(redis, "acme") == 0


async def test_different_tenants_have_independent_counts(redis):
    await sessions.mark_room_started(redis, "acme", "room1")
    await sessions.mark_room_started(redis, "other-tenant", "room1")
    assert await sessions.active_count(redis, "acme") == 1
    assert await sessions.active_count(redis, "other-tenant") == 1

    await sessions.mark_room_finished(redis, "acme", "room1")
    assert await sessions.active_count(redis, "acme") == 0
    assert await sessions.active_count(redis, "other-tenant") == 1


async def test_stale_entry_self_heals_via_native_redis_ttl(monkeypatch, redis):
    # Redis expires the key on its own — no app-code eviction check has to
    # run for a missed room_finished to self-heal.
    monkeypatch.setattr(config_module.settings, "active_session_ttl_seconds", 1)

    await sessions.mark_room_started(redis, "acme", "room1")
    assert await sessions.active_count(redis, "acme") == 1

    await asyncio.sleep(1.2)
    assert await sessions.active_count(redis, "acme") == 0
