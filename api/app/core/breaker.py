"""Circuit breaker for the upstream generator. See architecture.md section 10(c).

Retries with backoff handle a blip. They do not handle an outage: a thousand
queued jobs each burning three attempts against a dead endpoint turns our
retry policy into the thing keeping it down.

So after `threshold` consecutive failures the breaker opens, jobs stay QUEUED
instead of consuming attempts, and a single probe every `cooldown` seconds tests
recovery. Nothing is debited while the breaker is open, because submission
checks it before the transaction.

State lives in Redis so every worker and API instance shares one view.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = structlog.get_logger(__name__)

KEY: Final = "breaker:upstream"
THRESHOLD: Final = 5
COOLDOWN_SECONDS: Final = 30


class State(StrEnum):
    CLOSED = "closed"  # healthy, requests flow
    OPEN = "open"  # failing, requests refused without being attempted
    HALF_OPEN = "half_open"  # one probe allowed through


class CircuitBreaker:
    def __init__(
        self,
        redis: Redis,
        *,
        threshold: int = THRESHOLD,
        cooldown: int = COOLDOWN_SECONDS,
        key: str = KEY,
    ) -> None:
        self._redis = redis
        self._threshold = threshold
        self._cooldown = cooldown
        self._key = key

    async def state(self) -> State:
        try:
            raw = await self._redis.hgetall(self._key)  # type: ignore[misc]
        except Exception:
            # A breaker we cannot read must not block work: the retry budget
            # and the token bucket are still in force.
            log.error("breaker.redis_unavailable", exc_info=True)
            return State.CLOSED
        if not raw:
            return State.CLOSED
        failures = int(raw.get("failures", 0))
        if failures < self._threshold:
            return State.CLOSED
        opened_at = float(raw.get("openedAt", 0))
        if time.time() - opened_at >= self._cooldown:
            return State.HALF_OPEN
        return State.OPEN

    async def allows(self) -> bool:
        """True when a request may be attempted."""
        return await self.state() is not State.OPEN

    async def record_success(self) -> None:
        try:
            await self._redis.delete(self._key)
        except Exception:
            log.warning("breaker.reset_failed")

    async def record_failure(self) -> None:
        try:
            failures = await self._redis.hincrby(self._key, "failures", 1)  # type: ignore[misc]
            if failures >= self._threshold:
                # Stamp the opening time on the transition, and again on each
                # failed probe, so the cooldown restarts rather than letting a
                # still-broken upstream be probed on every job.
                await self._redis.hset(self._key, "openedAt", str(time.time()))  # type: ignore[misc]
                if failures == self._threshold:
                    log.error("breaker.opened", failures=failures)
            await self._redis.expire(self._key, self._cooldown * 20)
        except Exception:
            log.warning("breaker.record_failed")
