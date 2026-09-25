from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response

from app.core.errors import Forbidden, NotFound, PreconditionFailed
from app.core.sanitize import sanitize_search
from app.deps import DB, CurrentUser, OptionalUser, PageParams
from app.repositories.assets import AssetRepository
from app.schemas.asset import PublishIn
from app.services.feed import FeedService, asset_out

router = APIRouter(tags=["assets"])


@router.get("/library")
async def library(
    db: DB,
    user: CurrentUser,
    page: PageParams,
    response: Response,
    mode: Annotated[str | None, Query(pattern=r"^(image|motion)$")] = None,
    published: bool | None = None,
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    return await FeedService(db).library(
        str(user.id),
        cursor=page.cursor,
        limit=page.limit,
        mode=mode,
        published=published,
        q=sanitize_search(q),
    )


@router.get("/assets/{asset_id}")
async def get_asset(
    asset_id: str, db: DB, viewer: OptionalUser, response: Response
) -> dict[str, Any]:
    repo = AssetRepository(db)
    asset = await repo.by_id(asset_id)
    # 404 rather than 403 for someone else's private asset: a 403 confirms the
    # id exists, which is an enumeration oracle.
    if asset is None:
        raise NotFound("No such asset.")
    owned = viewer is not None and str(asset.userId) == str(viewer.id)
    if not asset.published and not owned:
        raise NotFound("No such asset.")
    liked = False
    if viewer is not None:
        liked = bool(await repo.liked_ids(str(viewer.id), [asset_id]))
    response.headers["ETag"] = f'"{asset.version}"'
    return asset_out(asset, liked=liked)


@router.patch("/assets/{asset_id}")
async def publish(
    asset_id: str,
    body: PublishIn,
    db: DB,
    user: CurrentUser,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, Any]:
    """Publish or unpublish. If-Match guards against a lost update."""
    repo = AssetRepository(db)
    asset = await repo.by_id(asset_id)
    if asset is None:
        raise NotFound("No such asset.")
    if str(asset.userId) != str(user.id):
        raise Forbidden("That is not yours to publish.")
    if asset.status != "READY":
        from app.core.errors import Conflict

        raise Conflict("That frame has not finished generating.")

    expected = None
    if if_match:
        try:
            expected = int(if_match.strip('"'))
        except ValueError as exc:
            raise PreconditionFailed("Malformed If-Match.") from exc

    updated = await repo.set_published(
        asset_id, published=body.published, expected_version=expected
    )
    if updated is None:
        raise PreconditionFailed("That asset changed since you loaded it.")
    return asset_out(updated)


@router.delete("/assets/{asset_id}", status_code=204)
async def delete_asset(asset_id: str, db: DB, user: CurrentUser) -> Response:
    removed = await AssetRepository(db).soft_delete(asset_id, str(user.id))
    if removed == 0:
        raise NotFound("No such asset.")
    return Response(status_code=204)


@router.put("/assets/{asset_id}/like", status_code=204)
async def like(asset_id: str, db: DB, user: CurrentUser) -> Response:
    repo = AssetRepository(db)
    if await repo.by_id(asset_id) is None:
        raise NotFound("No such asset.")
    await repo.like(str(user.id), asset_id)
    return Response(status_code=204)


@router.delete("/assets/{asset_id}/like", status_code=204)
async def unlike(asset_id: str, db: DB, user: CurrentUser) -> Response:
    await AssetRepository(db).unlike(str(user.id), asset_id)
    return Response(status_code=204)
