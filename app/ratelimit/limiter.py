"""Per-tenant sliding-window rate limit for widget token issuance, backed by
Redis. Deliberately isolated from the token endpoint so it's testable
against fakeredis without a live Redis server (see tests/test_limiter.py).
"""

import time
import uuid
from typing import Optional

from redis.asyncio import Redis

from ..config import settings

WINDOW_SECONDS = 60


async def check_and_increment(redis: Redis, site_id: str, limit: Optional[int] = None) -> bool:
    """Records one request for `site_id` and returns whether it's allowed
    under `limit` requests per WINDOW_SECONDS (default: settings value).
    Sliding-window log via a Redis sorted set, scored by request time."""
    limit = limit if limit is not None else settings.token_rate_limit_per_minute
    key = f"ratelimit:token:{site_id}"
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
