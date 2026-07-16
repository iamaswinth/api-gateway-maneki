from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from .db import close_pool, get_pool
from .forward.routes import router as forward_router
from .internal.routes import router as internal_router
from .redis_client import close_redis, get_redis
from .tenants.routes import router as tenants_router
from .webhooks.routes import router as webhooks_router
from .widget.routes import router as widget_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    await get_redis()
    yield
    await close_pool()
    await close_redis()


app = FastAPI(title="Maneki API Gateway", version="0.1.0", lifespan=lifespan)

# Permissive CORS is safe here: the app has no cookie-based auth anywhere
# (owner routes use Bearer JWTs, widget/internal routes use Bearer tokens),
# so a wildcard origin doesn't create a CSRF surface — a page on another
# origin still can't forge a valid credential it doesn't already have. The
# actual per-tenant Origin check for /widget/token lives in the handler
# (app/widget/routes.py), which needs the real request body (site_id) to
# resolve — something a CORS preflight can't see, so restricting this
# middleware to a fixed origin list isn't an option for that endpoint.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tenants_router)
app.include_router(widget_router)
app.include_router(webhooks_router)
app.include_router(forward_router)
app.include_router(internal_router)


async def _db_reachable() -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False


async def _redis_reachable() -> bool:
    try:
        await get_redis().ping()
        return True
    except Exception:
        return False


@app.get("/health")
async def health() -> dict:
    """Full diagnostic view for humans/dashboards — not a routing signal,
    so a downed dependency reports "degraded" at 200, not 503. Point
    orchestrator probes at /health/live and /health/ready instead."""
    db_ok = await _db_reachable()
    redis_ok = await _redis_reachable()
    return {
        "status": "ok" if db_ok and redis_ok else "degraded",
        "database_reachable": db_ok,
        "redis_reachable": redis_ok,
    }


@app.get("/health/live")
async def health_live() -> dict:
    """Liveness: no dependency checks, ever. Proves only that the process
    is up and the event loop is responsive. A k8s liveness probe must never
    depend on a downstream service — a transient DB/Redis blip would make
    k8s kill and restart an otherwise-healthy pod, which doesn't fix the
    dependency and can trigger a restart storm. See /health/ready for the
    dependency-aware check."""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready(response: Response) -> dict:
    """Readiness: pings the real Postgres pool and Redis. Point the load
    balancer / k8s readiness probe here — routing traffic to a worker that
    can't reach its DB or Redis just turns every request into a 500."""
    db_ok = await _db_reachable()
    redis_ok = await _redis_reachable()
    ok = db_ok and redis_ok
    if not ok:
        response.status_code = 503
    return {
        "status": "ok" if ok else "down",
        "database_reachable": db_ok,
        "redis_reachable": redis_ok,
    }
