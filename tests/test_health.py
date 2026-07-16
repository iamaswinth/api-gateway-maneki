"""/health/live must never fail on a downstream outage; /health/ready must
always fail (503) when Postgres or Redis is unreachable; /health reports
"degraded" (still 200) under the same conditions, since it's a diagnostic
view rather than a routing signal.
"""

from httpx import ASGITransport, AsyncClient

from app import main as main_module
from app.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class _BrokenRedis:
    async def ping(self):
        raise ConnectionError("redis is down")


async def _broken_get_pool():
    raise ConnectionError("db is down")


async def test_health_ok_when_dependencies_reachable():
    async with await _client() as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "database_reachable": True, "redis_reachable": True}


async def test_live_always_ok_even_if_db_and_redis_broken(monkeypatch):
    monkeypatch.setattr(main_module, "get_pool", _broken_get_pool)
    monkeypatch.setattr(main_module, "get_redis", lambda: _BrokenRedis())
    async with await _client() as client:
        resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_ready_ok_when_dependencies_reachable():
    async with await _client() as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "database_reachable": True, "redis_reachable": True}


async def test_ready_503_when_db_unreachable(monkeypatch):
    monkeypatch.setattr(main_module, "get_pool", _broken_get_pool)
    async with await _client() as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "down"
    assert body["database_reachable"] is False
    assert body["redis_reachable"] is True


async def test_ready_503_when_redis_unreachable(monkeypatch):
    monkeypatch.setattr(main_module, "get_redis", lambda: _BrokenRedis())
    async with await _client() as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "down"
    assert body["database_reachable"] is True
    assert body["redis_reachable"] is False


async def test_degraded_not_503_when_redis_unreachable(monkeypatch):
    monkeypatch.setattr(main_module, "get_redis", lambda: _BrokenRedis())
    async with await _client() as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["redis_reachable"] is False
