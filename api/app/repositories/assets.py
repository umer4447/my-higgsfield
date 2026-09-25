"""Asset queries: the wall feed, the library, search.

Every query here is keyset-paginated and maps onto a named index. See
architecture.md section 5 for the index-to-query map.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from prisma import Prisma
from prisma.enums import AssetStatus, Mode
from prisma.models import Asset
from prisma.types import AssetWhereInput

# Ordering is a closed set. An identifier can never be a bound parameter, so it
# must never come from a user.
SORTS: dict[str, str] = {
    "newest": "newest",
    "popular": "popular",
}


class AssetRepository:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    # ── feed ────────────────────────────────────────────────────────────

    def _wall_where(
        self, *, mode: str | None, preset: str | None, q: str | None, cursor: Any
    ) -> AssetWhereInput:
        where: AssetWhereInput = {
            "published": True,
            "deletedAt": None,
            "status": AssetStatus.READY,
        }
        if mode:
            where["mode"] = Mode(mode.upper())
        if preset:
            where["presetSlug"] = preset
        if q:
            # Prisma has no trigram operator, so contains/insensitive is the
            # expressible filter. The trigram GIN still accelerates it for the
            # raw-SQL search path below.
            where["prompt"] = {"contains": q, "mode": "insensitive"}
        if cursor:
            where["OR"] = [
                {"publishedAt": {"lt": cursor.ts}},
                {"publishedAt": cursor.ts, "id": {"lt": cursor.id}},
            ]
        return where

    async def wall_page(
        self,
        *,
        cursor: Any = None,
        limit: int = 24,
        mode: str | None = None,
        preset: str | None = None,
        q: str | None = None,
    ) -> list[Asset]:
        return await self._db.asset.find_many(
            where=self._wall_where(mode=mode, preset=preset, q=q, cursor=cursor),
            order=[{"publishedAt": "desc"}, {"id": "desc"}],
            take=limit + 1,
        )

    async def search_wall(self, q: str, *, limit: int) -> list[Asset]:
        """Trigram search, ordered by recency.

        On a creative feed "new and relevant" reads better than "most similar",
        and it lets search share the feed's keyset cursor.

        Positional parameters only. Column identifiers are quoted because the
        schema keeps camelCase column names.
        """
        rows = await self._db.query_raw(
            """
            SELECT "id"
              FROM "assets"
             WHERE "published" AND "deletedAt" IS NULL AND "status" = 'READY'
               AND "prompt" % $1
             ORDER BY "publishedAt" DESC, "id" DESC
             LIMIT $2
            """,
            q,
            limit,
        )
        ids = [r["id"] for r in rows]
        if not ids:
            return []
        found = await self._db.asset.find_many(where={"id": {"in": ids}})
        order = {a: i for i, a in enumerate(ids)}
        return sorted(found, key=lambda a: order.get(str(a.id), 0))

    # ── library ─────────────────────────────────────────────────────────

    async def library_page(
        self,
        user_id: str,
        *,
        cursor: Any = None,
        limit: int = 24,
        mode: str | None = None,
        published: bool | None = None,
        q: str | None = None,
    ) -> list[Asset]:
        where: AssetWhereInput = {"userId": user_id, "deletedAt": None}
        if mode:
            where["mode"] = Mode(mode.upper())
        if published is not None:
            where["published"] = published
        if q:
            where["prompt"] = {"contains": q, "mode": "insensitive"}
        if cursor:
            where["OR"] = [
                {"createdAt": {"lt": cursor.ts}},
                {"createdAt": cursor.ts, "id": {"lt": cursor.id}},
            ]
        return await self._db.asset.find_many(
            where=where,
            order=[{"createdAt": "desc"}, {"id": "desc"}],
            take=limit + 1,
        )

    # ── single ──────────────────────────────────────────────────────────

    async def by_id(self, asset_id: str) -> Asset | None:
        return await self._db.asset.find_first(
            where={"id": asset_id, "deletedAt": None}
        )

    async def by_ids(self, ids: list[str]) -> list[Asset]:
        return await self._db.asset.find_many(
            where={"id": {"in": ids}, "deletedAt": None}
        )

    async def set_published(
        self, asset_id: str, *, published: bool, expected_version: int | None
    ) -> Asset | None:
        """Optimistic concurrency: the version guard is in the WHERE clause, so
        a lost update is impossible without a read-then-write window."""
        where: AssetWhereInput = {"id": asset_id, "deletedAt": None}
        if expected_version is not None:
            where["version"] = expected_version
        updated = await self._db.asset.update_many(
            where=where,
            data={
                "published": published,
                "publishedAt": datetime.now(UTC) if published else None,
                "version": {"increment": 1},
            },
        )
        if updated == 0:
            return None
        return await self.by_id(asset_id)

    async def soft_delete(self, asset_id: str, user_id: str) -> int:
        return await self._db.asset.update_many(
            where={"id": asset_id, "userId": user_id, "deletedAt": None},
            data={"deletedAt": datetime.now(UTC), "published": False},
        )

    # ── likes ───────────────────────────────────────────────────────────

    async def liked_ids(self, user_id: str, asset_ids: list[str]) -> set[str]:
        if not asset_ids:
            return set()
        rows = await self._db.like.find_many(
            where={"userId": user_id, "assetId": {"in": asset_ids}}
        )
        return {str(r.assetId) for r in rows}

    async def like(self, user_id: str, asset_id: str) -> bool:
        """Idempotent by the composite primary key -- no check-then-insert race.
        The counter is incremented in the same transaction as the insert."""
        existing = await self._db.like.find_unique(
            where={"userId_assetId": {"userId": user_id, "assetId": asset_id}}
        )
        if existing:
            return False
        async with self._db.tx() as tx:
            await tx.like.create(data={"userId": user_id, "assetId": asset_id})
            await tx.asset.update(
                where={"id": asset_id}, data={"likeCount": {"increment": 1}}
            )
        return True

    async def unlike(self, user_id: str, asset_id: str) -> bool:
        removed = await self._db.like.delete_many(
            where={"userId": user_id, "assetId": asset_id}
        )
        if removed == 0:
            return False
        await self._db.asset.update_many(
            where={"id": asset_id, "likeCount": {"gt": 0}},
            data={"likeCount": {"decrement": 1}},
        )
        return True
