"""app/ratelimit/sessions.py in isolation, against fakeredis."""

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


async def test_stale_entry_evicted_by_ttl_guard(monkeypatch, redis):
    current_time = [1_000_000.0]
    monkeypatch.setattr(sessions.time, "time", lambda: current_time[0])
    monkeypatch.setattr(config_module.settings, "active_session_ttl_seconds", 100)

    await sessions.mark_room_started(redis, "acme", "room1")
    assert await sessions.active_count(redis, "acme") == 1

    current_time[0] += 200
    assert await sessions.active_count(redis, "acme") == 0
