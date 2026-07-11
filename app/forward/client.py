"""Thin async HTTP client to the ingestion service. Wire contracts are
duplicated in app/forward/models.py rather than imported — same pattern
voice_runtime and ingestion already use toward each other, since the two
services are deployed and versioned independently.
"""

from typing import Optional

import httpx

from ..config import settings


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.ingestion_base_url, timeout=settings.ingestion_timeout_seconds
    )


async def post(
    path: str, json: Optional[dict] = None, params: Optional[dict] = None
) -> httpx.Response:
    async with _client() as client:
        return await client.post(path, json=json, params=params)


async def get(path: str, params: Optional[dict] = None) -> httpx.Response:
    async with _client() as client:
        return await client.get(path, params=params)
