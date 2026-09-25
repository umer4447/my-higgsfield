"""Job submission: validate, price, debit, enqueue.

The order matters and is the whole design. Everything that can reject the
request happens before the transaction, the transaction is short and touches
only the database, and the task is enqueued after commit.
"""

from __future__ import annotations

import contextlib
import random
from typing import TYPE_CHECKING, Any

import structlog
from prisma import Prisma
from prisma.enums import AssetStatus, JobStatus, Move
from prisma.errors import UniqueViolationError

from app.core.breaker import CircuitBreaker
from app.core.errors import (
    Conflict,
    NotFound,
    PlanForbids,
    QueueFull,
    RateLimited,
    UpstreamFailed,
)
from app.core.idempotency import IdempotencyStore, request_hash
from app.core.sanitize import compose_prompt
from app.core.throttle import ConcurrencyThrottle
from app.repositories.jobs import JobRepository
from app.services import credit
from app.services.catalog import CatalogService
from app.services.pricing import Price, price_job

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = structlog.get_logger(__name__)


def random_seed() -> int:
    return random.randint(1000, 9_999_999)  # noqa: S311  -- not security-relevant


class JobService:
    def __init__(self, db: Prisma, redis: Redis) -> None:
        self._db = db
        self._redis = redis
        self._jobs = JobRepository(db)
        self._catalog = CatalogService(db, redis)
        self._throttle = ConcurrencyThrottle(redis)
        self._breaker = CircuitBreaker(redis)
        self._idem = IdempotencyStore(redis)

    # ── pricing ─────────────────────────────────────────────────────────

    async def quote(
        self,
        *,
        model_id: str,
        batch: int,
        preset_slug: str | None,
        credits_available: int,
    ) -> dict[str, Any]:
        model, _, preset = await self._catalog.resolve(model_id, "1:1", preset_slug)
        if model is None:
            raise NotFound("No such model.")
        if preset_slug and preset is None:
            raise NotFound("No such preset.")
        if batch > model.maxBatch:
            raise Conflict(
                f"{model.name} generates at most {model.maxBatch} at a time."
            )
        p = price_job(model.creditCost, batch, bool(preset and preset.move))
        return {
            "base": p.base,
            "moveSurcharge": p.move_surcharge,
            "total": p.total,
            "creditCostPerOutput": p.per_output,
            "affordable": credits_available >= p.total,
            "creditsAvailable": credits_available,
        }

    # ── compatibility ───────────────────────────────────────────────────

    def _assert_compatible(
        self, user: Any, model: Any, preset: Any, batch: int
    ) -> None:
        plan = user.plan
        if model.mode == "MOTION" and not plan.motionEnabled:
            raise PlanForbids(
                f"Motion models need the Studio plan. You are on {plan.name}."
            )
        if batch > model.maxBatch:
            raise Conflict(
                f"{model.name} generates at most {model.maxBatch} at a time."
            )
        if batch > plan.maxBatch:
            raise PlanForbids(f"{plan.name} allows batches up to {plan.maxBatch}.")
        # A still can take any preset -- a motion preset applied to a still is
        # just its look without the move, which is a legitimate thing to want.
        # A motion job is the constrained direction: it needs a preset that
        # carries a camera move, because the move is what is being rendered.
        if model.mode == "MOTION" and preset is not None and preset.move is None:
            raise Conflict(
                f"{model.name} makes motion, and the {preset.name} preset "
                "carries no camera move. Pick a preset that does, or none."
            )

    # ── submit ──────────────────────────────────────────────────────────

    async def submit(
        self, *, user: Any, body: dict[str, Any], idempotency_key: str
    ) -> tuple[Any, bool]:
        """Returns (job, replayed)."""
        replayed = await self._idem.replay(user.id, idempotency_key)
        if replayed is not None:
            if replayed.get("requestHash") != request_hash(body):
                raise Conflict("That idempotency key was used for a different request.")
            job = await self._jobs.by_id(replayed["jobId"])
            if job is not None:
                return job, True

        if not await self._idem.claim(user.id, idempotency_key):
            raise Conflict("A request with this key is already in flight.")

        try:
            return await self._submit_inner(user, body, idempotency_key), False
        except Exception:
            await self._idem.release(user.id, idempotency_key)
            raise

    async def _submit_inner(
        self, user: Any, body: dict[str, Any], idempotency_key: str
    ) -> Any:
        model, ratio, preset = await self._catalog.resolve(
            body["modelId"], body["ratioId"], body.get("presetSlug")
        )
        if model is None or ratio is None:
            raise NotFound("No such model or aspect ratio.")
        if body.get("presetSlug") and preset is None:
            raise NotFound("No such preset.")

        self._assert_compatible(user, model, preset, body["batch"])

        price: Price = price_job(
            model.creditCost, body["batch"], bool(preset and preset.move)
        )

        # Backpressure before the debit. Never take the money and then admit we
        # cannot do the work.
        from app.config import get_settings

        if await self._jobs.queue_depth() >= get_settings().max_queue_depth:
            raise QueueFull()

        # Checked before the transaction: never take the credits for work we
        # already know cannot be done.
        if not await self._breaker.allows():
            raise UpstreamFailed(
                "The generator is down. Nothing was charged; try again shortly."
            )

        composed = compose_prompt(body["prompt"], preset.template if preset else None)
        move: Move | None = (preset.move if preset else None) or (
            Move.PUSH if model.mode == "MOTION" else None
        )

        job_id: str
        async with self._db.tx() as tx:
            job = await tx.job.create(
                data={
                    "userId": user.id,
                    "idempotencyKey": idempotency_key,
                    "requestHash": request_hash(body),
                    "mode": model.mode,
                    "prompt": body["prompt"],
                    "composedPrompt": composed,
                    "modelId": model.id,
                    "presetSlug": preset.slug if preset else None,
                    "ratioId": ratio.id,
                    "batch": body["batch"],
                    "seed": body.get("seed"),
                    "move": move,
                    "creditsDebited": price.total,
                }
            )
            job_id = job.id

            # Seeds are resolved here, not at generation time. That is what
            # makes Remix exact and generation deterministic and retryable.
            base_seed = body.get("seed")
            for i in range(body["batch"]):
                seed = (base_seed + i) if base_seed is not None else random_seed()
                await tx.asset.create(
                    data={
                        "userId": user.id,
                        "jobId": job_id,
                        "mode": model.mode,
                        "status": AssetStatus.PENDING,
                        "prompt": body["prompt"],
                        "composedPrompt": composed,
                        "modelId": model.id,
                        "presetSlug": preset.slug if preset else None,
                        "ratioId": ratio.id,
                        "seed": seed,
                        "move": move,
                        "width": ratio.width,
                        "height": ratio.height,
                        "creditCost": model.creditCost,
                        "authorHandle": user.handle or "you",
                    }
                )

            await credit.debit(
                tx,
                user_id=user.id,
                amount=price.total,
                job_id=job_id,
                note=f"{body['batch']} x {model.name}",
            )
        # committed

        # Concurrency permit after the money is settled; releasing it is the
        # worker's job, in a finally.
        if not await self._throttle.acquire(
            user.id, job_id, user.plan.maxConcurrentJobs
        ):
            await self._cancel_and_refund(job_id, user.id, price.total)
            raise RateLimited(retry_after=15, reason="concurrency")

        await self._enqueue(job_id)
        await self._idem.store(
            user.id,
            idempotency_key,
            {"jobId": job_id, "requestHash": request_hash(body)},
        )
        loaded = await self._jobs.by_id(job_id)
        assert loaded is not None
        return loaded

    async def _cancel_and_refund(self, job_id: str, user_id: str, amount: int) -> None:
        await self._jobs.finish(
            job_id, JobStatus.CANCELLED, "Too many jobs already running."
        )
        await credit.refund(
            self._db,
            user_id=user_id,
            job_id=job_id,
            amount=amount,
            note="cancelled before it ran",
        )

    async def _enqueue(self, job_id: str) -> None:
        """After commit, never inside the transaction.

        A task enqueued inside a transaction that rolls back leaves a worker
        hunting a job that does not exist. A task lost after commit is picked
        up by the sweeper. Losing work is recoverable; inventing work is not.
        """
        try:
            from arq.connections import ArqRedis

            from app.workers.queue import enqueue_generate

            await enqueue_generate(self._redis, job_id)
            _ = ArqRedis
        except Exception:
            log.error("jobs.enqueue_failed", job_id=job_id, exc_info=True)

    # ── cancel ──────────────────────────────────────────────────────────

    async def cancel(self, job_id: str, user: Any) -> Any:
        job = await self._jobs.by_id(job_id)
        if job is None or str(job.userId) != str(user.id):
            raise NotFound("No such job.")
        if await self._jobs.cancel_if_queued(job_id, user.id) == 0:
            raise Conflict("That job already started; it cannot be cancelled.")
        outstanding = job.creditsDebited - job.creditsRefunded
        # Already refunded is the success case here, not an error.
        with contextlib.suppress(UniqueViolationError):
            await credit.refund(
                self._db,
                user_id=user.id,
                job_id=job_id,
                amount=outstanding,
                note="cancelled before it ran",
            )
        await self._throttle.release(user.id, job_id)
        result = await self._jobs.by_id(job_id)
        assert result is not None
        return result
