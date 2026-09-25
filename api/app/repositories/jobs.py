from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from prisma import Prisma
from prisma.enums import JobStatus
from prisma.models import Job
from prisma.types import JobWhereInput

ACTIVE: list[JobStatus] = [JobStatus.QUEUED, JobStatus.RUNNING]
TERMINAL: list[JobStatus] = [
    JobStatus.SUCCEEDED,
    JobStatus.PARTIAL,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
]


class JobRepository:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def by_id(self, job_id: str) -> Job | None:
        return await self._db.job.find_unique(
            where={"id": job_id}, include={"outputs": True}
        )

    async def by_idempotency_key(self, user_id: str, key: str) -> Job | None:
        return await self._db.job.find_unique(
            where={"userId_idempotencyKey": {"userId": user_id, "idempotencyKey": key}},
            include={"outputs": True},
        )

    async def page(
        self,
        user_id: str,
        *,
        cursor: Any = None,
        limit: int = 24,
        status: str | None = None,
    ) -> list[Job]:
        where: JobWhereInput = {"userId": user_id}
        if status == "active":
            # prisma-client-py types WhereInput.status as a bare enum and does
            # not model the {"in": [...]} filter form, which Prisma supports at
            # runtime. Narrow cast rather than losing the filter.
            where["status"] = cast("Any", {"in": ACTIVE})
        elif status:
            where["status"] = JobStatus(status.upper())
        if cursor:
            where["OR"] = [
                {"createdAt": {"lt": cursor.ts}},
                {"createdAt": cursor.ts, "id": {"lt": cursor.id}},
            ]
        return await self._db.job.find_many(
            where=where,
            order=[{"createdAt": "desc"}, {"id": "desc"}],
            take=limit + 1,
            include={"outputs": True},
        )

    async def queue_depth(self) -> int:
        where: JobWhereInput = {"status": cast("Any", {"in": ACTIVE})}
        return await self._db.job.count(where=where)

    async def mark_running(self, job_id: str) -> int:
        """Guarded transition: only a QUEUED job starts, so a task delivered
        twice does not run twice."""
        return await self._db.job.update_many(
            where={"id": job_id, "status": JobStatus.QUEUED},
            data={
                "status": JobStatus.RUNNING,
                "startedAt": datetime.now(UTC),
                "attempts": {"increment": 1},
            },
        )

    async def finish(
        self, job_id: str, status: JobStatus, error: str | None = None
    ) -> None:
        await self._db.job.update(
            where={"id": job_id},
            data={
                "status": status,
                "finishedAt": datetime.now(UTC),
                "error": (error or "")[:500] or None,
            },
        )

    async def cancel_if_queued(self, job_id: str, user_id: str) -> int:
        return await self._db.job.update_many(
            where={"id": job_id, "userId": user_id, "status": JobStatus.QUEUED},
            data={"status": JobStatus.CANCELLED, "finishedAt": datetime.now(UTC)},
        )

    async def sweep_lost(self, older_than_seconds: int) -> list[Job]:
        """Recovers tasks lost between commit and enqueue. Losing work is
        recoverable; inventing work is not, which is why we enqueue after
        commit and sweep rather than enqueue inside the transaction."""
        cutoff = datetime.fromtimestamp(
            datetime.now(UTC).timestamp() - older_than_seconds, UTC
        )
        return await self._db.job.find_many(
            where={"status": JobStatus.QUEUED, "queuedAt": {"lt": cutoff}},
            order={"queuedAt": "asc"},
            take=50,
        )
