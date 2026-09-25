from typing import Annotated, Any

from fastapi import APIRouter, Query, Response

from app.core.sanitize import sanitize_search
from app.deps import DB, OptionalUser, PageParams
from app.services.feed import FeedService

router = APIRouter(tags=["wall"])


@router.get("/wall")
async def wall(
    db: DB,
    page: PageParams,
    viewer: OptionalUser,
    response: Response,
    mode: Annotated[str | None, Query(pattern=r"^(image|motion)$")] = None,
    preset: Annotated[str | None, Query(pattern=r"^[a-z0-9-]{2,64}$")] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
) -> dict[str, Any]:
    """The public feed. Every item carries the prompt that made it.

    Keyset-paged, so page 400 costs what page 1 costs.
    """
    response.headers["Cache-Control"] = (
        "public, max-age=15" if not viewer else "private, no-store"
    )
    return await FeedService(db).wall(
        cursor=page.cursor,
        limit=page.limit,
        mode=mode,
        preset=preset,
        q=sanitize_search(q),
        viewer_id=str(viewer.id) if viewer else None,
    )
