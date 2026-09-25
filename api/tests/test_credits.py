"""The money path. These are the tests that carry the design.

Everything else can be re-derived from the code; correct behaviour under a race
cannot.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.errors import InsufficientCredits
from app.services import credit


async def _job(db: Any, user: Any, cost: int, key: str) -> Any:
    return await db.job.create(
        data={
            "userId": user.id,
            "idempotencyKey": key,
            "requestHash": "0" * 64,
            "mode": "IMAGE",
            "prompt": "p",
            "composedPrompt": "p",
            "modelId": "halide-2",
            "ratioId": "1:1",
            "batch": 1,
            "creditsDebited": cost,
        }
    )


async def _ledger_sum(db: Any, user_id: str) -> int:
    rows = await db.query_raw(
        'SELECT COALESCE(SUM("delta"),0)::int AS t '
        'FROM "ledger_entries" WHERE "userId" = $1::uuid',
        user_id,
    )
    return int(rows[0]["t"])


async def test_concurrent_submits_cannot_overspend(db: Any, user: Any) -> None:
    """50 parallel debits of 18 against 40 credits: exactly 2 may succeed.

    This is what the conditional UPDATE and CHECK (credits >= 0) are for.
    """

    async def one(i: int) -> str:
        job = await _job(db, user, 18, f"k{i}")
        try:
            await credit.debit(db, user_id=user.id, amount=18, job_id=job.id)
        except InsufficientCredits:
            return "denied"
        return "ok"

    results = await asyncio.gather(*(one(i) for i in range(50)))
    assert results.count("ok") == 2, "40 credits buys exactly two 18-credit jobs"

    after = await db.user.find_unique(where={"id": user.id})
    assert after.credits >= 0
    assert after.credits == 4
    # The invariant, now exact: every credit a user holds came from a ledger
    # entry, including the signup grant, so the two sides agree with no offset.
    assert after.credits == await _ledger_sum(db, str(user.id))


async def test_balance_can_never_go_negative(db: Any, user: Any) -> None:
    """The database refuses, even if application logic were bypassed."""
    from prisma.errors import PrismaError

    with pytest.raises(PrismaError):
        await db.execute_raw(
            'UPDATE "users" SET "credits" = -1 WHERE "id" = $1::uuid', str(user.id)
        )


async def test_refund_is_idempotent(db: Any, user: Any) -> None:
    """UNIQUE (jobId, reason) makes a re-run of a crashed worker safe."""
    job = await _job(db, user, 18, "refund-once")
    await credit.debit(db, user_id=user.id, amount=18, job_id=job.id)

    first = await credit.refund(
        db, user_id=user.id, job_id=job.id, amount=18, note="all failed"
    )
    second = await credit.refund(
        db, user_id=user.id, job_id=job.id, amount=18, note="all failed"
    )

    assert first == 18
    assert second == 0, "the second refund must be a no-op, not a second payout"
    after = await db.user.find_unique(where={"id": user.id})
    assert after.credits == 40
    assert after.credits == await _ledger_sum(db, str(user.id))


async def test_partial_batch_refunds_only_failures(db: Any, user: Any) -> None:
    """A batch of 4 where 2 landed refunds 2, not 4."""
    job = await _job(db, user, 8, "partial")
    await credit.debit(db, user_id=user.id, amount=8, job_id=job.id)
    assert (await db.user.find_unique(where={"id": user.id})).credits == 32

    await credit.refund(
        db, user_id=user.id, job_id=job.id, amount=4, note="2 of 4 outputs failed"
    )
    after = await db.user.find_unique(where={"id": user.id})
    assert after.credits == 36
    assert after.credits == await _ledger_sum(db, str(user.id))


async def test_refund_cannot_exceed_debit(db: Any, user: Any) -> None:
    """CHECK (creditsRefunded <= creditsDebited) is the schema-level guard."""
    from prisma.errors import PrismaError

    job = await _job(db, user, 8, "over-refund")
    await credit.debit(db, user_id=user.id, amount=8, job_id=job.id)
    with pytest.raises(PrismaError):
        await db.job.update(where={"id": job.id}, data={"creditsRefunded": 99})


async def test_debit_rejects_non_positive(db: Any, user: Any) -> None:
    job = await _job(db, user, 1, "zero")
    with pytest.raises(ValueError, match="positive"):
        await credit.debit(db, user_id=user.id, amount=0, job_id=job.id)
