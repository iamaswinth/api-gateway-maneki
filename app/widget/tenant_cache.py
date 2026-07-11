"""Short-TTL cache in front of tenant_config reads for the widget token hot
path — avoids a DB round trip on every token request without going stale for
longer than settings.tenant_config_cache_seconds.
"""

import time
from typing import Optional

from ..config import settings
from ..tenants import store
from ..tenants.models import TenantConfig

_cache: dict[str, tuple[float, Optional[TenantConfig]]] = {}


async def get_cached_tenant(tenant_id: str) -> Optional[TenantConfig]:
    now = time.monotonic()
    cached = _cache.get(tenant_id)
    if cached is not None and (now - cached[0]) < settings.tenant_config_cache_seconds:
        return cached[1]
    tenant = await store.get_tenant(tenant_id)
    _cache[tenant_id] = (now, tenant)
    return tenant


def invalidate(tenant_id: str) -> None:
    _cache.pop(tenant_id, None)
