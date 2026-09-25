"""Rate limiting: requests per unit time.

State lives in Redis, never in process memory. A module-level counter resets on
every cold start and is not shared between instances, so it does not limit
anything. Check-and-increment is one atomic Lua script.

Fails open on a Redis outage and alerts, except the `generate` class, which
fails closed: spending credits with a broken limiter is worse than a brief
inability to generate. See architecture.md section 10.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = structlog.get_logger(__name__)

# Atomic sliding window. Trimming, counting and admitting in one round trip
# means two instances cannot both see room for the last request.
_SCRIPT: Final = """
local key, now = KEYS[1], tonumber(ARGV[1])
local window, limit = tonumber(ARGV[2]), tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local used = redis.call('ZCARD', key)
if used >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local reset = math.ceil((tonumber(oldest[2]) + window - now) / 1000)
  return {0, 0, reset}
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, window)
return {1, limit - used - 1, math.ceil(window / 1000)}
"""


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int

    def headers(self) -> dict[str, str]:
        h = {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(max(0, self.remaining)),
            "RateLimit-Reset": str(self.reset_seconds),
        }
        if not self.allowed:
            h["Retry-After"] = str(max(1, self.reset_seconds))
        return h


# Per-class limits per minute, by plan. One global number is either too strict
# for reads or too loose for generation. `search` is a fifth of `read` because
# a trigram scan costs far more than an index lookup.
LIMITS: Final[dict[str, dict[str, int]]] = {
    "read": {"darkroom-free": 120, "darkroom-studio": 300, "darkroom-plate": 600},
    "search": {"darkroom-free": 20, "darkroom-studio": 60, "darkroom-plate": 120},
    "write": {"darkroom-free": 30, "darkroom-studio": 90, "darkroom-plate": 180},
    "auth": {"darkroom-free": 10, "darkroom-studio": 10, "darkroom-plate": 10},
    "generate": {"darkroom-free": 6, "darkroom-studio": 30, "darkroom-plate": 90},
}
FAIL_CLOSED: Final = frozenset({"generate"})
WINDOW_MS: Final = 60_000


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._sha: str | None = None

    async def _eval(self, key: str, limit: int, member: str) -> list[int]:
        now = int(time.time() * 1000)
        args: list[Any] = [now, WINDOW_MS, limit, member]
        if self._sha is None:
            self._sha = await cast("Any", self._redis.script_load(_SCRIPT))
        try:
            return cast(
                "list[int]",
                await cast("Any", self._redis.evalsha(self._sha, 1, key, *args)),
            )
        except Exception as exc:  # script evicted by SCRIPT FLUSH
            if "NOSCRIPT" not in str(exc):
                raise
            self._sha = await cast("Any", self._redis.script_load(_SCRIPT))
            return cast(
                "list[int]",
                await cast("Any", self._redis.evalsha(self._sha, 1, key, *args)),
            )

    async def check(self, *, identity: str, klass: str, plan_id: str) -> Decision:
        limit = (
            LIMITS.get(klass, LIMITS["read"]).get(plan_id)
            or LIMITS["read"]["darkroom-free"]
        )
        key = f"rl:{klass}:{identity}"
        try:
            allowed, remaining, reset = await self._eval(key, limit, uuid.uuid4().hex)
        except Exception:
            log.error("ratelimit.redis_unavailable", klass=klass, exc_info=True)
            if klass in FAIL_CLOSED:
                return Decision(False, limit, 0, 30)
            return Decision(True, limit, limit, 60)
        return Decision(bool(allowed), limit, int(remaining), int(reset))
