from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import close_pool, get_pool
from .redis_client import close_redis, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    await get_redis()
    yield
    await close_pool()
    await close_redis()


app = FastAPI(title="Maneki API Gateway", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
