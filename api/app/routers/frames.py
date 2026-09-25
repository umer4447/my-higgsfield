from fastapi import APIRouter, Response

from app.core.errors import NotFound
from app.deps import DB, OptionalUser
from app.repositories.assets import AssetRepository
from app.services import storage

router = APIRouter(prefix="/frames", tags=["frames"])


@router.get("/{asset_id}")
async def frame(asset_id: str, db: DB, viewer: OptionalUser) -> Response:
    """Serve a generated frame.

    The client only ever holds this URL. The upstream and storage locations are
    never exposed, which is what closes the SSRF door the client-side design
    left open.
    """
    asset = await AssetRepository(db).by_id(asset_id)
    if asset is None or asset.status != "READY" or not asset.storageKey:
        raise NotFound("No such frame.")
    owned = viewer is not None and str(asset.userId) == str(viewer.id)
    if not asset.published and not owned:
        raise NotFound("No such frame.")

    store = storage.get_storage()
    if not store.exists(asset.storageKey):
        raise NotFound("That frame is no longer stored.")

    import anyio

    data = await anyio.to_thread.run_sync(store.read, asset.storageKey)
    return Response(
        content=data,
        media_type=store.content_type(asset.storageKey),
        headers={
            # Content-addressed, so immutable is honest.
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{asset.contentHash}"',
        },
    )
