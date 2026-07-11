"""Active concurrent-session counting for max_concurrent_sessions enforcement.

One Redis key per active room, with a native `EX` expiry
(settings.active_session_ttl_seconds) — so a missed room_finished webhook
self-heals because Redis itself reaps the key, not because app code happens
to run an eviction check. `mark_room_started` is naturally idempotent: a
duplicate room_started delivery just re-issues SET ... EX on the same key,
resetting the TTL rather than double-counting.
"""

from redis.asyncio import Redis

from ..config import settings


def _key(tenant_id: str, room_name: str) -> str:
    return f"sessions:active:{tenant_id}:{room_name}"


def _pattern(tenant_id: str) -> str:
    return f"sessions:active:{tenant_id}:*"


async def active_count(redis: Redis, tenant_id: str) -> int:
    count = 0
    async for _ in redis.scan_iter(match=_pattern(tenant_id), count=100):
        count += 1
    return count


async def mark_room_started(redis: Redis, tenant_id: str, room_name: str) -> None:
    await redis.set(_key(tenant_id, room_name), "1", ex=settings.active_session_ttl_seconds)


async def mark_room_finished(redis: Redis, tenant_id: str, room_name: str) -> None:
    await redis.delete(_key(tenant_id, room_name))
