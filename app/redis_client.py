"""Shared async Redis client. Backs rate-limit windows (app/ratelimit/limiter.py)
and active-session counts (app/ratelimit/sessions.py) — nothing else in the
Maneki stack uses Redis today, so this is new infra scoped to this service.
"""

from typing import Optional

import redis.asyncio as redis

from .config import settings

_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
