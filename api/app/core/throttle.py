"""Throttling: concurrent work in flight.

Rate limiting caps arrival; throttling caps simultaneity, which is what
actually protects the upstream generator and our own worker pool. This is the
server-side replacement for the client's MAX_IN_FLIGHT queue and the frame
proxy's MIN_GAP_MS -- same idea, now shared across instances.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Final, cast

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = structlog.get_logger(__name__)

# A permit TTL longer than the job timeout, so a crashed worker cannot leak a
# permit forever.
PERMIT_TTL_SECONDS: Final = 600

_ACQUIRE: Final = """
local key, limit, member, ttl = KEYS[1], tonumber(ARGV[1]), ARGV[2], tonumber(ARGV[3])
local now = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, 0, now - ttl)
if redis.call('ZCARD', key) >= limit then return 0 end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, ttl)
return 1
"""

# Token bucket for the upstream. Per-user limits do not protect a third party:
# a thousand users each within their limit still overwhelm one endpoint.
_BUCKET: Final = """
local key, rate = KEYS[1], tonumber(ARGV[1])
local capacity, now = tonumber(ARGV[2]), tonumber(ARGV[3])
local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1]) or capacity
local ts = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + (now - ts) * rate)
if tokens < 1 then
  redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
  redis.call('EXPIRE', key, 120)
  return math.ceil((1 - tokens) / rate * 1000)
end
redis.call('HMSET', key, 'tokens', tokens - 1, 'ts', now)
redis.call('EXPIRE', key, 120)
return 0
"""


class ConcurrencyThrottle:
    """Per-user in-flight job permits, sized by the user's plan."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _key(user_id: str) -> str:
        return f"throttle:jobs:{user_id}"

    async def acquire(self, user_id: str, job_id: str, limit: int) -> bool:
        try:
            # redis-py types eval() arguments as str; Lua takes numbers here.
            got = await cast("Any", self._redis).eval(
                _ACQUIRE,
                1,
                self._key(user_id),
                limit,
                job_id,
                PERMIT_TTL_SECONDS,
                int(time.time()),
            )
            return bool(got)
        except Exception:
            # Availability over protection: the DB still enforces credits.
            log.error("throttle.redis_unavailable", user_id=user_id, exc_info=True)
            return True

    async def release(self, user_id: str, job_id: str) -> None:
        try:
            await self._redis.zrem(self._key(user_id), job_id)
        except Exception:
            log.warning("throttle.release_failed", user_id=user_id, job_id=job_id)

    async def in_flight(self, user_id: str) -> int:
        try:
            return int(await self._redis.zcard(self._key(user_id)))
        except Exception:
            return 0


class UpstreamBucket:
    """Global token bucket in front of the generator."""

    def __init__(self, redis: Redis, *, rate: float, capacity: int) -> None:
        self._redis, self._rate, self._capacity = redis, rate, capacity

    async def take(self) -> float:
        """Return seconds to wait; 0 means a token was granted."""
        try:
            wait_ms = await cast("Any", self._redis).eval(
                _BUCKET,
                1,
                "throttle:upstream",
                self._rate,
                self._capacity,
                time.time(),
            )
            return float(wait_ms) / 1000.0
        except Exception:
            log.error("bucket.redis_unavailable", exc_info=True)
            return 1.0 / max(self._rate, 0.1)
