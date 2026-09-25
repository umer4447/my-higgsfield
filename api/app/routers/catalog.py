from fastapi import APIRouter, Request, Response

from app.deps import DB, RedisDep
from app.services.catalog import CatalogService

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("")
async def get_catalog(
    request: Request, response: Response, db: DB, redis: RedisDep
) -> object:
    """Models, presets, ratios and plans in one request.

    Changes on deploy, not per user, so it is cached hard with an ETag.
    """
    service = CatalogService(db, redis)
    payload, etag = await service.payload()
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = (
        "public, max-age=300, stale-while-revalidate=3600"
    )
    return payload
