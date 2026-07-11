"""Request body the gateway accepts for the scrape-forwarding endpoint.

Same shape as the ingestion service's `ScrapeRequest`
(Firecrawl-scraper-ingestion/app/models.py) minus `tenant_id` — the gateway
injects that itself from the authenticated, ownership-checked path param and
never trusts a caller-supplied one.
"""

from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class ScrapeForwardRequest(BaseModel):
    url: HttpUrl
    limit: Optional[int] = Field(default=None, ge=1)
    include_paths: Optional[list[str]] = None
    exclude_paths: Optional[list[str]] = None
    wait_for: Optional[int] = Field(default=None, ge=0)
