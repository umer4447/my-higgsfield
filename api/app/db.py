"""The Prisma client and Redis connection, created once at startup.

Connection churn against a pooled Postgres turns a 15ms endpoint into a 300ms
one, so neither of these is ever created per request.
"""

from __future__ import annotations

from prisma import Prisma
from redis.asyncio import Redis

from app.config import get_settings

_db: Prisma | None = None
_redis: Redis | None = None


async def connect() -> tuple[Prisma, Redis]:
    global _db, _redis
    settings = get_settings()
    # No auto_register: it registers the client in a process-global, so a
    # second app instance (every test) collides. Nothing here uses the
    # registered-model API -- all access goes through this client instance.
    _db = Prisma(datasource={"url": settings.database_url})
    await _db.connect()
    _redis = Redis.from_url(str(settings.redis_url), decode_responses=True)
    await _redis.ping()
    return _db, _redis


async def disconnect() -> None:
    global _db, _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
    if _db is not None and _db.is_connected():
        await _db.disconnect()
        _db = None


def db() -> Prisma:
    if _db is None:
        raise RuntimeError("Database is not connected. Call connect() first.")
    return _db


def redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis is not connected. Call connect() first.")
    return _redis
