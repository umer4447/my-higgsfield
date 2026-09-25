"""Idempotency for writes that spend money.

Two layers, each covering the other's failure: Redis makes a retry fast, and
UNIQUE (userId, idempotencyKey) on jobs makes a double charge impossible even
with Redis cold. The database constraint is the guarantee.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis

TTL_SECONDS = 86_400
LOCK_TTL_SECONDS = 60


def request_hash(payload: dict[str, Any]) -> str:
    """Stable digest of a request body, so the same key with a different body
    can be rejected instead of silently replaying the wrong response."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


class IdempotencyStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _key(user_id: str, key: str) -> str:
        return f"idem:{user_id}:{key}"

    @staticmethod
    def _lock(user_id: str, key: str) -> str:
        return f"idem-lock:{user_id}:{key}"

    async def replay(self, user_id: str, key: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._key(user_id, key))
        return json.loads(raw) if raw else None

    async def claim(self, user_id: str, key: str) -> bool:
        """NX before the work, so two simultaneous retries cannot both proceed."""
        got = await self._redis.set(
            self._lock(user_id, key), "1", nx=True, ex=LOCK_TTL_SECONDS
        )
        return bool(got)

    async def store(self, user_id: str, key: str, response: dict[str, Any]) -> None:
        await self._redis.set(
            self._key(user_id, key), json.dumps(response, default=str), ex=TTL_SECONDS
        )
        await self._redis.delete(self._lock(user_id, key))

    async def release(self, user_id: str, key: str) -> None:
        await self._redis.delete(self._lock(user_id, key))
