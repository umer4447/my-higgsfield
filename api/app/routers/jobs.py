import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.core.errors import NotFound
from app.core.pagination import build_page
from app.deps import DB, CurrentUser, IdempotencyKey, PageParams, RedisDep
from app.repositories.jobs import JobRepository
from app.schemas.job import QuoteIn, SubmitJobIn
from app.services.feed import job_out
from app.services.jobs import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/quote")
async def quote(
    body: QuoteIn, db: DB, redis: RedisDep, user: CurrentUser
) -> dict[str, Any]:
    """Itemised cost, computed by the same function that performs the debit.

    Cost before you spend is a product promise, so the number on the button
    comes from the server that will charge it.
    """
    return await JobService(db, redis).quote(
        model_id=body.model_id,
        batch=body.batch,
        preset_slug=body.preset_slug,
        credits_available=user.credits,
    )


@router.post("", status_code=201)
async def submit(
    body: SubmitJobIn,
    db: DB,
    redis: RedisDep,
    user: CurrentUser,
    key: IdempotencyKey,
    response: Response,
) -> dict[str, Any]:
    job, replayed = await JobService(db, redis).submit(
        user=user,
        body=body.model_dump(by_alias=True, exclude_none=False),
        idempotency_key=key,
    )
    if replayed:
        response.status_code = 200
        response.headers["Idempotency-Replayed"] = "true"
    return job_out(job)


@router.get("")
async def list_jobs(
    db: DB,
    user: CurrentUser,
    page: PageParams,
    status: Annotated[
        str | None,
        Query(pattern=r"^(active|queued|running|succeeded|partial|failed|cancelled)$"),
    ] = None,
) -> dict[str, Any]:
    rows = await JobRepository(db).page(
        str(user.id), cursor=page.cursor, limit=page.limit, status=status
    )
    result = build_page(rows, page.limit, ts_field="createdAt")
    return {
        "data": [job_out(j) for j in result.data],
        "meta": {
            "nextCursor": result.next_cursor,
            "hasMore": result.has_more,
            "limit": page.limit,
        },
    }


@router.get("/stream")
async def stream(
    request: Request, redis: RedisDep, user: CurrentUser
) -> StreamingResponse:
    """Server-sent events for the job tray.

    One connection per tab replaces per-second polling of every in-flight job.
    The client falls back to polling after two stream errors, because mobile
    Safari and corporate proxies both drop long-lived connections.
    """
    from app.workers.queue import STREAM_CHANNEL

    channel = f"{STREAM_CHANNEL}:{user.id}"

    async def events() -> Any:
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            yield 'event: ready\ndata: {"ok":true}\n\n'
            while True:
                if await request.is_disconnected():
                    break
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=15.0
                )
                if msg is None:
                    yield ": keepalive\n\n"
                    continue
                payload = json.loads(msg["data"])
                body = json.dumps(payload["data"])
                yield f"event: {payload['event']}\ndata: {body}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[no-untyped-call]

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Tells nginx and friends not to buffer the stream.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            # Declaring an encoding stops anything in front of us applying one.
            # The Next.js rewrite proxy gzips this route otherwise, and gzip
            # buffers: the browser's EventSource then receives nothing at all
            # until the buffer flushes, which on an idle stream is never. curl
            # hides the problem because it does not send Accept-Encoding by
            # default -- only a real browser shows it.
            "Content-Encoding": "identity",
        },
    )


@router.get("/{job_id}")
async def get_job(job_id: str, db: DB, user: CurrentUser) -> dict[str, Any]:
    job = await JobRepository(db).by_id(job_id)
    if job is None or str(job.userId) != str(user.id):
        raise NotFound("No such job.")
    return job_out(job)


@router.post("/{job_id}/cancel")
async def cancel(
    job_id: str, db: DB, redis: RedisDep, user: CurrentUser
) -> dict[str, Any]:
    return job_out(await JobService(db, redis).cancel(job_id, user))
