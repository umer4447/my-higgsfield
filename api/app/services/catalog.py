"""Catalog reads, cached.

The catalog changes on deploy, not per user, so it is one request cached hard.
Pricing and model availability must be changeable without a frontend deploy,
which is why this lives in Postgres rather than in a TypeScript constant.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from typing import TYPE_CHECKING, Any

from prisma import Prisma

from app.repositories.catalog import CatalogRepository

if TYPE_CHECKING:
    from redis.asyncio import Redis

CACHE_KEY = "catalog:v1"
CACHE_TTL = 300


class CatalogService:
    def __init__(self, db: Prisma, redis: Redis) -> None:
        self._repo = CatalogRepository(db)
        self._redis = redis

    async def payload(self) -> tuple[dict[str, Any], str]:
        """Return the catalog and a strong ETag over its content."""
        cached = None
        with contextlib.suppress(Exception):
            cached = await self._redis.get(CACHE_KEY)

        if cached:
            data = json.loads(cached)
        else:
            data = await self._repo.as_payload()
            # A cache outage must degrade performance, not availability.
            with contextlib.suppress(Exception):
                await self._redis.set(
                    CACHE_KEY, json.dumps(data, default=str), ex=CACHE_TTL
                )

        blob = json.dumps(data, sort_keys=True, default=str).encode()
        return data, f'"{hashlib.sha256(blob).hexdigest()[:32]}"'

    async def invalidate(self) -> None:
        await self._redis.delete(CACHE_KEY)

    # Direct lookups used on the submit path. These hit Postgres by primary
    # key, which is already a sub-millisecond index lookup.
    async def resolve(
        self, model_id: str, ratio_id: str, preset_slug: str | None
    ) -> tuple[Any, Any, Any]:
        model = await self._repo.model(model_id)
        ratio = await self._repo.ratio(ratio_id)
        preset = await self._repo.preset(preset_slug) if preset_slug else None
        return model, ratio, preset

    async def plan(self, plan_id: str) -> Any:
        return await self._repo.plan(plan_id)
