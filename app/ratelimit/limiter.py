"""Generic sliding-window rate limit, backed by Redis. Dimension-agnostic —
callers build the key (e.g. "token:{site_id}" for per-tenant limits,
"ip:{client_ip}" for a global per-client admission check) and pass an
explicit limit, since different dimensions have different budgets. Isolated
from any endpoint so it's testable against fakeredis without a live Redis
server (see tests/test_limiter.py).
"""

import time
import uuid

from redis.asyncio import Redis

WINDOW_SECONDS = 60


async def check_and_increment(redis: Redis, key: str, limit: int) -> bool:
    """Records one request for `key` and returns whether it's allowed under
    `limit` requests per WINDOW_SECONDS. Sliding-window log via a Redis
    sorted set, scored by request time."""
    key = f"ratelimit:{key}"
    now = time.time()
    window_start = now - WINDOW_SECONDS
    member = f"{now}:{uuid.uuid4()}"

    async with redis.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, WINDOW_SECONDS)
        _, _, count, _ = await pipe.execute()

    if count > limit:
        await redis.zrem(key, member)
        return False
    return True
