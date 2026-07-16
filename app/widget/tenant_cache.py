"""Redis-backed cache in front of tenant_config reads for the widget token hot
path — avoids a DB round trip on every token request without going stale for
longer than settings.tenant_config_cache_seconds. Backed by Redis rather than
an in-process dict so publish/unpublish/update invalidation
(app/tenants/routes.py) is immediate across every worker and replica, not
just the one that handled the mutation — this cache sits directly in front
of the widget token security boundary (app/widget/routes.py), so "unpublish"
must not keep other workers handing out tokens for up to
tenant_config_cache_seconds after the owner hit the button.
"""

import json
from typing import Optional

from ..config import settings
from ..redis_client import get_redis
from ..tenants import store
from ..tenants.models import TenantConfig

_KEY_PREFIX = "tenant_cache:"


def _key(tenant_id: str) -> str:
    return f"{_KEY_PREFIX}{tenant_id}"


async def get_cached_tenant(tenant_id: str) -> Optional[TenantConfig]:
    redis = get_redis()
    cached = await redis.get(_key(tenant_id))
    if cached is not None:
        data = json.loads(cached)
        return TenantConfig.model_validate(data) if data is not None else None

    tenant = await store.get_tenant(tenant_id)
    value = tenant.model_dump_json() if tenant is not None else "null"
    await redis.set(_key(tenant_id), value, ex=settings.tenant_config_cache_seconds)
    return tenant


async def invalidate(tenant_id: str) -> None:
    await get_redis().delete(_key(tenant_id))
