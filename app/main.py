from contextlib import asynccontextmanager

from fastapi import FastAPI
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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
