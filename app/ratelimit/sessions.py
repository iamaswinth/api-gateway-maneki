"""Active concurrent-session counting for max_concurrent_sessions enforcement.

Backed by a per-tenant Redis hash (room_name -> started_at timestamp) rather
than a plain counter, so a duplicate room_started webhook delivery is
naturally idempotent (re-setting the same field), and `active_count` lazily
evicts any room whose entry has outlived settings.active_session_ttl_seconds
— a reconcile guard against a missed room_finished webhook permanently
holding a tenant's concurrency slot.
"""

import time

from redis.asyncio import Redis

from ..config import settings


def _key(tenant_id: str) -> str:
    return f"sessions:active:{tenant_id}"


async def active_count(redis: Redis, tenant_id: str) -> int:
    key = _key(tenant_id)
    cutoff = time.time() - settings.active_session_ttl_seconds
    entries = await redis.hgetall(key)
    stale = [room for room, started_at in entries.items() if float(started_at) < cutoff]
    if stale:
        await redis.hdel(key, *stale)
    return len(entries) - len(stale)


async def mark_room_started(redis: Redis, tenant_id: str, room_name: str) -> None:
    await redis.hset(_key(tenant_id), room_name, str(time.time()))


async def mark_room_finished(redis: Redis, tenant_id: str, room_name: str) -> None:
    await redis.hdel(_key(tenant_id), room_name)
