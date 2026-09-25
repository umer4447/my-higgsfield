"""The money path. See architecture.md section 6.

Invariants, all enforced by the database rather than by application care:
  1. A balance is never negative        -> CHECK (credits >= 0)
  2. A job is debited exactly once      -> UNIQUE (userId, idempotencyKey)
  3. A job is refunded at most once     -> UNIQUE (jobId, reason)
  4. credits == SUM(ledger.delta)       -> reconciliation job
"""

from __future__ import annotations

import structlog
from prisma import Prisma
from prisma.enums import LedgerReason
from prisma.errors import UniqueViolationError

from app.core.errors import InsufficientCredits

log = structlog.get_logger(__name__)


async def debit(
    db: Prisma, *, user_id: str, amount: int, job_id: str, note: str | None = None
) -> int:
    """Atomically spend `amount`; return the new balance.

    The conditional UPDATE does the balance check and the decrement in one
    statement, so there is no read-then-write window for two concurrent submits
    to race through. Zero rows updated means the user could not afford it and
    nothing changed.
    """
    if amount <= 0:
        raise ValueError("debit amount must be positive")

    rows = await db.query_raw(
        """
        UPDATE "users"
           SET "credits" = "credits" - $2, "updatedAt" = now()
         WHERE "id" = $1::uuid AND "credits" >= $2 AND "deletedAt" IS NULL
        RETURNING "credits"
        """,
        user_id,
        amount,
    )
    if not rows:
        current = await db.user.find_unique(where={"id": user_id})
        raise InsufficientCredits(
            required=amount, available=current.credits if current else 0
        )

    balance = int(rows[0]["credits"])
    await db.ledgerentry.create(
        data={
            "userId": user_id,
            "jobId": job_id,
            "reason": LedgerReason.JOB_DEBIT,
            "delta": -amount,
            "balanceAfter": balance,
            "note": note,
        }
    )
    return balance


async def refund(
    db: Prisma, *, user_id: str, job_id: str, amount: int, note: str
) -> int:
    """Refund failed outputs. Idempotent by UNIQUE (jobId, reason).

    A worker that crashes after refunding but before marking the job done can
    safely re-run: the second attempt hits the constraint and we treat it as
    already applied.
    """
    if amount <= 0:
        return 0
    try:
        async with db.tx() as tx:
            rows = await tx.query_raw(
                'UPDATE "users" SET "credits" = "credits" + $2, "updatedAt" = now() '
                'WHERE "id" = $1::uuid RETURNING "credits"',
                user_id,
                amount,
            )
            balance = int(rows[0]["credits"])
            await tx.ledgerentry.create(
                data={
                    "userId": user_id,
                    "jobId": job_id,
                    "reason": LedgerReason.JOB_REFUND,
                    "delta": amount,
                    "balanceAfter": balance,
                    "note": note[:200],
                }
            )
            await tx.job.update(where={"id": job_id}, data={"creditsRefunded": amount})
    except UniqueViolationError:
        log.info("credits.refund_already_applied", job_id=job_id)
        return 0
    return amount


async def grant(
    db: Prisma,
    *,
    user_id: str,
    amount: int,
    reason: LedgerReason,
    note: str | None = None,
) -> int:
    rows = await db.query_raw(
        'UPDATE "users" SET "credits" = "credits" + $2, "updatedAt" = now() '
        'WHERE "id" = $1::uuid RETURNING "credits"',
        user_id,
        amount,
    )
    balance = int(rows[0]["credits"])
    await db.ledgerentry.create(
        data={
            "userId": user_id,
            "reason": reason,
            "delta": amount,
            "balanceAfter": balance,
            "note": note,
        }
    )
    return balance
