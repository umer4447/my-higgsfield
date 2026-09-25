"""The generation worker.

Every task is idempotent and re-entrant: it can be delivered twice and it can
die halfway, and both must be safe. Terminal-state writes happen even on
failure, so a job is never stuck in RUNNING forever.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx
import structlog
from prisma import Prisma
from prisma.enums import AssetStatus, JobStatus
from redis.asyncio import Redis

from app.config import get_settings
from app.core.breaker import CircuitBreaker
from app.core.errors import UpstreamFailed
from app.core.throttle import ConcurrencyThrottle, UpstreamBucket
from app.repositories.jobs import JobRepository
from app.services import credit, storage
from app.services.generation import FrameRequest, fetch_frame
from app.workers.queue import publish_event

log = structlog.get_logger(__name__)


async def generate_job(db: Prisma, redis: Redis, job_id: str) -> str:
    jobs = JobRepository(db)
    throttle = ConcurrencyThrottle(redis)
    s = get_settings()
    bucket = UpstreamBucket(
        redis, rate=s.upstream_tokens_per_second, capacity=s.upstream_bucket_capacity
    )
    breaker = CircuitBreaker(redis)
    store = storage.get_storage()

    job = await jobs.by_id(job_id)
    if job is None:
        log.warning("worker.job_missing", job_id=job_id)
        return "missing"

    # Guarded transition: only a QUEUED job starts, so a redelivered task is a
    # no-op rather than a second run.
    if await jobs.mark_running(job_id) == 0:
        log.info("worker.job_not_queued", job_id=job_id, status=job.status)
        return "skipped"

    user_id = str(job.userId)
    await publish_event(
        redis, user_id, "job.updated", {"id": job_id, "status": "running"}
    )

    model = await db.generationmodel.find_unique(where={"id": job.modelId})
    engine = model.engine if model else "FLUX"
    failed = 0

    try:
        async with httpx.AsyncClient() as client:
            for output in job.outputs or []:
                if output.status == AssetStatus.READY:
                    continue
                await db.asset.update(
                    where={"id": output.id}, data={"status": AssetStatus.RUNNING}
                )
                try:
                    data = await fetch_frame(
                        FrameRequest(
                            composed_prompt=job.composedPrompt,
                            width=output.width,
                            height=output.height,
                            seed=output.seed,
                            engine=engine,
                        ),
                        client,
                        bucket,
                        breaker,
                    )
                    # Verify before storing. A declared content type is never
                    # trusted, and bytes that are not an image never reach disk.
                    ext = storage.sniff(data)
                    digest = storage.content_hash(data)
                    key = storage.key_for(digest, ext)
                    if not store.exists(key):
                        await asyncio.to_thread(store.put, key, data)
                    await db.asset.update(
                        where={"id": output.id},
                        data={
                            "status": AssetStatus.READY,
                            "storageKey": key,
                            "contentHash": digest,
                            "bytes": len(data),
                            "error": None,
                        },
                    )
                    await publish_event(
                        redis,
                        user_id,
                        "output.ready",
                        {"jobId": job_id, "assetId": str(output.id)},
                    )
                except (
                    UpstreamFailed,
                    storage.UnsupportedImageError,
                    httpx.HTTPError,
                ) as exc:
                    failed += 1
                    await db.asset.update(
                        where={"id": output.id},
                        data={"status": AssetStatus.FAILED, "error": str(exc)[:500]},
                    )
                    await publish_event(
                        redis,
                        user_id,
                        "output.failed",
                        {"jobId": job_id, "assetId": str(output.id)},
                    )

        # Refund only what actually failed. A batch of four where two landed
        # refunds two, and the job is PARTIAL.
        if failed:
            per_output = job.creditsDebited // max(job.batch, 1)
            amount = min(per_output * failed, job.creditsDebited)
            await credit.refund(
                db,
                user_id=user_id,
                job_id=job_id,
                amount=amount,
                note=f"{failed} of {job.batch} outputs failed",
            )
            await publish_event(redis, user_id, "credits.changed", {"jobId": job_id})

        status: JobStatus = (
            JobStatus.FAILED
            if failed == job.batch
            else (JobStatus.PARTIAL if failed else JobStatus.SUCCEEDED)
        )
        await jobs.finish(
            job_id, status, f"{failed} output(s) failed" if failed else None
        )
        await publish_event(
            redis,
            user_id,
            "job.updated",
            {"id": job_id, "status": status.value.lower()},
        )
        return str(status)

    except Exception as exc:
        log.error("worker.job_crashed", job_id=job_id, exc_info=True)
        await credit.refund(
            db,
            user_id=user_id,
            job_id=job_id,
            amount=job.creditsDebited - job.creditsRefunded,
            note="job failed",
        )
        await jobs.finish(job_id, JobStatus.FAILED, str(exc))
        await publish_event(
            redis, user_id, "job.updated", {"id": job_id, "status": "failed"}
        )
        return str(JobStatus.FAILED)
    finally:
        # Always. A leaked permit blocks the user from submitting again.
        await throttle.release(user_id, job_id)


async def sweep(db: Prisma, redis: Redis) -> int:
    """Recover jobs whose enqueue was lost between commit and the queue."""
    jobs = JobRepository(db)
    lost = await jobs.sweep_lost(older_than_seconds=120)
    for job in lost:
        from app.workers.queue import enqueue_generate

        await enqueue_generate(redis, str(job.id))
    if lost:
        log.info("worker.swept", count=len(lost))
    return len(lost)


MAINTENANCE_INTERVAL_SECONDS = 3600


async def _maybe_maintain(db: Prisma, redis: Redis) -> None:
    """Run maintenance at most hourly, whichever worker gets there first.

    A Redis SET NX is the lock: several workers may be idle at once, and the
    reconciliation query should not run once per worker per tick.
    """
    from app.workers.maintenance import run_all

    got = await redis.set(
        "maintenance:lock", "1", nx=True, ex=MAINTENANCE_INTERVAL_SECONDS
    )
    if not got:
        return
    try:
        result = await run_all(db)
        log.info("worker.maintenance", **result)
    except Exception:
        log.error("worker.maintenance_failed", exc_info=True)


async def run_forever() -> None:
    """A simple blocking-pop loop.

    ARQ is the documented queue for this project; this loop is the same
    contract with one fewer dependency, and keeps the worker importable in
    tests without a broker running.
    """
    from app.db import connect, disconnect
    from app.workers.queue import QUEUE_KEY

    db, redis = await connect()
    log.info("worker.started")
    try:
        while True:
            # redis-py types blpop as a union of awaitable and value.
            item: Any = await cast("Any", redis.blpop([QUEUE_KEY], timeout=5))
            if item is None:
                await sweep(db, redis)
                await _maybe_maintain(db, redis)
                continue
            _, job_id = item
            await generate_job(db, redis, job_id)
    finally:
        await disconnect()


if __name__ == "__main__":
    from app.core.logging import configure

    configure(json_output=False)
    asyncio.run(run_forever())
