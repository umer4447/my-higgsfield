"""Serialisation for assets and jobs, plus the two paged reads.

Response shapes are built here rather than returned straight from Prisma rows:
returning a row leaks storageKey, contentHash and deletedAt into a public API.
"""

from __future__ import annotations

from typing import Any

from prisma import Prisma

from app.config import get_settings
from app.core.pagination import Cursor, build_page
from app.repositories.assets import AssetRepository


def frame_url(asset: Any) -> str | None:
    """The client only ever sees our own URL, never an upstream or storage one."""
    if asset.status != "READY":
        return None
    return f"{get_settings().storage_public_base_url}/{asset.id}"


def asset_out(asset: Any, *, liked: bool = False) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "mode": asset.mode.lower(),
        "status": asset.status.lower(),
        "prompt": asset.prompt,
        "composedPrompt": asset.composedPrompt,
        "modelId": asset.modelId,
        "presetSlug": asset.presetSlug,
        "ratioId": asset.ratioId,
        "seed": asset.seed,
        "move": asset.move.lower() if asset.move else None,
        "width": asset.width,
        "height": asset.height,
        "creditCost": asset.creditCost,
        "authorHandle": asset.authorHandle,
        "published": asset.published,
        "likeCount": asset.likeCount,
        "likedByMe": liked,
        "seeded": asset.seeded,
        "url": frame_url(asset),
        "version": asset.version,
        "createdAt": asset.createdAt,
    }


def job_out(job: Any) -> dict[str, Any]:
    outputs = sorted(job.outputs or [], key=lambda a: a.seed)
    return {
        "id": str(job.id),
        "status": job.status.lower(),
        "mode": job.mode.lower(),
        "prompt": job.prompt,
        "composedPrompt": job.composedPrompt,
        "modelId": job.modelId,
        "presetSlug": job.presetSlug,
        "ratioId": job.ratioId,
        "batch": job.batch,
        "move": job.move.lower() if job.move else None,
        "creditsDebited": job.creditsDebited,
        "creditsRefunded": job.creditsRefunded,
        "error": job.error,
        "createdAt": job.createdAt,
        "finishedAt": job.finishedAt,
        "outputs": [
            {
                "id": str(o.id),
                "status": o.status.lower(),
                "seed": o.seed,
                "width": o.width,
                "height": o.height,
                "url": frame_url(o),
                "error": o.error,
            }
            for o in outputs
        ],
    }


class FeedService:
    def __init__(self, db: Prisma) -> None:
        self._assets = AssetRepository(db)

    async def _decorate(
        self, rows: list[Any], viewer_id: str | None
    ) -> list[dict[str, Any]]:
        liked: set[str] = set()
        if viewer_id and rows:
            liked = await self._assets.liked_ids(viewer_id, [str(r.id) for r in rows])
        return [asset_out(r, liked=str(r.id) in liked) for r in rows]

    async def wall(
        self,
        *,
        cursor: Cursor | None,
        limit: int,
        mode: str | None,
        preset: str | None,
        q: str | None,
        viewer_id: str | None,
    ) -> dict[str, Any]:
        rows = await self._assets.wall_page(
            cursor=cursor, limit=limit, mode=mode, preset=preset, q=q
        )
        page = build_page(rows, limit, ts_field="publishedAt")
        return {
            "data": await self._decorate(page.data, viewer_id),
            "meta": {
                "nextCursor": page.next_cursor,
                "hasMore": page.has_more,
                "limit": limit,
            },
        }

    async def library(
        self,
        user_id: str,
        *,
        cursor: Cursor | None,
        limit: int,
        mode: str | None,
        published: bool | None,
        q: str | None,
    ) -> dict[str, Any]:
        rows = await self._assets.library_page(
            user_id, cursor=cursor, limit=limit, mode=mode, published=published, q=q
        )
        page = build_page(rows, limit, ts_field="createdAt")
        return {
            "data": await self._decorate(page.data, user_id),
            "meta": {
                "nextCursor": page.next_cursor,
                "hasMore": page.has_more,
                "limit": limit,
            },
        }
