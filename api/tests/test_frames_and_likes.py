"""Serving frames, and the like counter.

The frame route is what makes the SSRF story true: the client only ever holds
our own URL, never an upstream or storage location.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services import storage

# A one-pixel JPEG. Magic bytes matter: the sniffer rejects anything else.
JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300"
    "0806060706050807070709090808" + "0a" * 50 + "ffd9"
)


@pytest.fixture
async def ready_asset(db: Any, user: Any) -> Any:
    digest = storage.content_hash(JPEG)
    key = storage.key_for(digest, "jpg")
    storage.reset_storage_cache()
    storage.get_storage().put(key, JPEG)
    return await db.asset.create(
        data={
            "userId": user.id,
            "mode": "IMAGE",
            "status": "READY",
            "prompt": "a stored frame",
            "composedPrompt": "a stored frame",
            "modelId": "halide-2",
            "ratioId": "1:1",
            "seed": 7,
            "width": 832,
            "height": 832,
            "creditCost": 2,
            "authorHandle": "tester",
            "storageKey": key,
            "contentHash": digest,
            "bytes": len(JPEG),
        }
    )


async def test_owner_can_fetch_an_unpublished_frame(
    client: Any, db: Any, ready_asset: Any, user: Any
) -> None:
    me = (await client.post("/v1/auth/anonymous")).json()
    await db.asset.update(where={"id": ready_asset.id}, data={"userId": me["id"]})

    r = await client.get(f"/v1/frames/{ready_asset.id}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == JPEG
    # Content-addressed, so immutable is an honest claim.
    assert "immutable" in r.headers["cache-control"]
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_a_strangers_unpublished_frame_is_404(
    client: Any, ready_asset: Any
) -> None:
    await client.post("/v1/auth/anonymous")
    assert (await client.get(f"/v1/frames/{ready_asset.id}")).status_code == 404


async def test_published_frames_are_public(
    client: Any, db: Any, ready_asset: Any
) -> None:
    await db.asset.update(where={"id": ready_asset.id}, data={"published": True})
    r = await client.get(f"/v1/frames/{ready_asset.id}")
    assert r.status_code == 200
    assert r.content == JPEG


async def test_pending_asset_has_no_frame_and_no_url(
    client: Any, db: Any, user: Any
) -> None:
    pending = await db.asset.create(
        data={
            "userId": user.id,
            "mode": "IMAGE",
            "status": "PENDING",
            "prompt": "not yet",
            "composedPrompt": "not yet",
            "modelId": "halide-2",
            "ratioId": "1:1",
            "seed": 1,
            "width": 832,
            "height": 832,
            "creditCost": 2,
            "authorHandle": "tester",
            "published": True,
        }
    )
    assert (await client.get(f"/v1/frames/{pending.id}")).status_code == 404
    await client.post("/v1/auth/anonymous")
    # And the API never hands out a URL for a frame that does not exist yet.
    body = (await client.get("/v1/wall?limit=60")).json()["data"]
    for item in body:
        if item["status"] != "ready":
            assert item["url"] is None


async def test_the_client_never_receives_an_upstream_or_storage_url(
    client: Any, db: Any, ready_asset: Any
) -> None:
    await db.asset.update(where={"id": ready_asset.id}, data={"published": True})
    body = (await client.get(f"/v1/assets/{ready_asset.id}")).json()
    assert body["url"] == f"/v1/frames/{ready_asset.id}"
    blob = str(body)
    # The storage key, the content hash and any external host must not appear.
    # The public URL legitimately contains "/v1/frames/"; the storage key
    # ("frames/ab/<sha>.jpg") must not.
    assert ready_asset.storageKey not in blob
    assert ready_asset.contentHash not in blob
    for leak in ("pollinations", "http://", "https://", "s3.", ".amazonaws"):
        assert leak not in blob, f"{leak} leaked into the asset payload"
    assert "storageKey" not in blob and "contentHash" not in blob


# ── likes ───────────────────────────────────────────────────────────────


async def test_like_is_idempotent_and_counts_once(
    client: Any, db: Any, ready_asset: Any
) -> None:
    await db.asset.update(where={"id": ready_asset.id}, data={"published": True})
    await client.post("/v1/auth/anonymous")

    before = (await client.get(f"/v1/assets/{ready_asset.id}")).json()["likeCount"]
    assert (await client.put(f"/v1/assets/{ready_asset.id}/like")).status_code == 204
    assert (await client.put(f"/v1/assets/{ready_asset.id}/like")).status_code == 204

    body = (await client.get(f"/v1/assets/{ready_asset.id}")).json()
    assert body["likeCount"] == before + 1, "the composite PK makes this idempotent"
    assert body["likedByMe"] is True


async def test_unlike_decrements_and_never_goes_negative(
    client: Any, db: Any, ready_asset: Any
) -> None:
    await db.asset.update(where={"id": ready_asset.id}, data={"published": True})
    await client.post("/v1/auth/anonymous")

    await client.put(f"/v1/assets/{ready_asset.id}/like")
    await client.delete(f"/v1/assets/{ready_asset.id}/like")
    body = (await client.get(f"/v1/assets/{ready_asset.id}")).json()
    assert body["likeCount"] == 0
    assert body["likedByMe"] is False

    # Unliking again is a no-op, not a negative counter.
    await client.delete(f"/v1/assets/{ready_asset.id}/like")
    assert (await client.get(f"/v1/assets/{ready_asset.id}")).json()["likeCount"] == 0


async def test_liking_a_missing_asset_is_404(client: Any) -> None:
    import uuid

    await client.post("/v1/auth/anonymous")
    r = await client.put(f"/v1/assets/{uuid.uuid4()}/like")
    assert r.status_code == 404


# ── publish ─────────────────────────────────────────────────────────────


async def test_publish_requires_a_ready_frame(client: Any, db: Any, user: Any) -> None:
    me = (await client.post("/v1/auth/anonymous")).json()
    pending = await db.asset.create(
        data={
            "userId": me["id"],
            "mode": "IMAGE",
            "status": "PENDING",
            "prompt": "not yet",
            "composedPrompt": "not yet",
            "modelId": "halide-2",
            "ratioId": "1:1",
            "seed": 1,
            "width": 832,
            "height": 832,
            "creditCost": 2,
            "authorHandle": "tester",
        }
    )
    r = await client.patch(f"/v1/assets/{pending.id}", json={"published": True})
    assert r.status_code == 409


async def test_stale_if_match_is_412(client: Any, db: Any, ready_asset: Any) -> None:
    """Optimistic concurrency: a lost update is refused, not silently applied."""
    me = (await client.post("/v1/auth/anonymous")).json()
    await db.asset.update(where={"id": ready_asset.id}, data={"userId": me["id"]})

    ok = await client.patch(
        f"/v1/assets/{ready_asset.id}",
        json={"published": True},
        headers={"If-Match": '"1"'},
    )
    assert ok.status_code == 200

    stale = await client.patch(
        f"/v1/assets/{ready_asset.id}",
        json={"published": False},
        headers={"If-Match": '"1"'},
    )
    assert stale.status_code == 412


async def test_soft_delete_hides_the_asset_everywhere(
    client: Any, db: Any, ready_asset: Any
) -> None:
    me = (await client.post("/v1/auth/anonymous")).json()
    await db.asset.update(
        where={"id": ready_asset.id}, data={"userId": me["id"], "published": True}
    )
    assert (await client.delete(f"/v1/assets/{ready_asset.id}")).status_code == 204

    assert (await client.get(f"/v1/assets/{ready_asset.id}")).status_code == 404
    assert (await client.get(f"/v1/frames/{ready_asset.id}")).status_code == 404
    ids = {a["id"] for a in (await client.get("/v1/wall?limit=60")).json()["data"]}
    assert str(ready_asset.id) not in ids
    # Soft, not hard: the row survives for audit.
    row = await db.asset.find_unique(where={"id": ready_asset.id})
    assert row is not None and row.deletedAt is not None
