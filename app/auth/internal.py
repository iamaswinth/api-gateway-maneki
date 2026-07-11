"""Service-to-service auth for the voice runtime's internal tenant-config
read (app/internal/routes.py). Distinct trust level from Clerk owner JWTs
(app/auth/clerk.py) and anonymous widget tokens (app/widget/) — this token
type is never accepted on an owner or widget route, and neither of those is
ever accepted here.
"""

import hmac
from typing import Optional

from fastapi import Header, HTTPException

from ..config import settings


async def require_internal_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[len("Bearer "):]
    if not settings.internal_token or not hmac.compare_digest(token, settings.internal_token):
        raise HTTPException(status_code=401, detail="Invalid internal token")
