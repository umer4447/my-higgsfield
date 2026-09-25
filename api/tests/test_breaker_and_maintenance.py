"""Circuit breaker and the scheduled maintenance jobs."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.breaker import CircuitBreaker, State
from app.services import credit
from app.workers.maintenance import (
    reap_anonymous_users,
    reconcile_ledger,
    refresh_monthly_credits,
)

# ── breaker ─────────────────────────────────────────────────────────────


async def test_breaker_starts_closed(redis_client: Any) -> None:
    b = CircuitBreaker(redis_client, key="breaker:test")
    assert await b.state() is State.CLOSED
    assert await b.allows() is True


async def test_breaker_opens_after_the_threshold(redis_client: Any) -> None:
    b = CircuitBreaker(redis_client, threshold=3, cooldown=60, key="breaker:test")
    for _ in range(2):
        await b.record_failure()
    assert await b.state() is State.CLOSED, "below the threshold it stays closed"

    await b.record_failure()
    assert await b.state() is State.OPEN
    assert await b.allows() is False


async def test_success_closes_the_breaker(redis_client: Any) -> None:
    b = CircuitBreaker(redis_client, threshold=2, cooldown=60, key="breaker:test")
    await b.record_failure()
    await b.record_failure()
    assert await b.state() is State.OPEN

    await b.record_success()
    assert await b.state() is State.CLOSED
    assert await b.allows() is True


async def test_breaker_half_opens_after_the_cooldown(redis_client: Any) -> None:
    """One probe is allowed through, rather than staying open forever."""
    b = CircuitBreaker(redis_client, threshold=1, cooldown=1, key="breaker:test")
    await b.record_failure()
    assert await b.state() is State.OPEN

    await redis_client.hset("breaker:test", "openedAt", str(time.time() - 5))
    assert await b.state() is State.HALF_OPEN
    assert await b.allows() is True, "a half-open breaker admits a probe"


async def test_a_failed_probe_restarts_the_cooldown(redis_client: Any) -> None:
    """Otherwise every queued job probes a still-dead upstream."""
    b = CircuitBreaker(redis_client, threshold=1, cooldown=30, key="breaker:test")
    await b.record_failure()
    await redis_client.hset("breaker:test", "openedAt", str(time.time() - 60))
    assert await b.state() is State.HALF_OPEN

    await b.record_failure()
    assert await b.state() is State.OPEN


async def test_submission_is_refused_while_the_breaker_is_open(
    client: Any, redis_client: Any
) -> None:
    """Refused before the transaction, so nothing is charged for work we
    already know cannot be done."""
    from tests.conftest import key, make_job_body

    await client.post("/v1/auth/anonymous")
    for _ in range(5):
        await CircuitBreaker(redis_client).record_failure()

    r = await client.post(
        "/v1/jobs", json=make_job_body(), headers={"Idempotency-Key": key()}
    )
    assert r.status_code == 502
    assert "Nothing was charged" in r.json()["detail"]
    assert (await client.get("/v1/me")).json()["credits"] == 40


# ── reconciliation ──────────────────────────────────────────────────────


async def test_reconciliation_is_clean_for_honest_accounts(db: Any, user: Any) -> None:
    await credit.grant(
        db, user_id=user.id, amount=10, reason="ADMIN_ADJUSTMENT", note="t"
    )
    drift = await reconcile_ledger(db)
    assert all(d.user_id != str(user.id) for d in drift)


async def test_reconciliation_detects_tampering(db: Any, user: Any) -> None:
    """The one alert that pages immediately: the balance and the ledger
    disagree, so one of them is lying about money."""
    await db.execute_raw(
        'UPDATE "users" SET "credits" = "credits" + 999 WHERE "id" = $1::uuid',
        str(user.id),
    )
    drift = await reconcile_ledger(db)
    mine = [d for d in drift if d.user_id == str(user.id)]
    assert len(mine) == 1
    assert mine[0].delta == 999, "the drift reported must be the amount injected"
    assert mine[0].credits != mine[0].ledger_sum


# ── reaping ─────────────────────────────────────────────────────────────


async def test_reaping_removes_idle_empty_anonymous_accounts(db: Any) -> None:
    stale = await db.user.create(
        data={
            "planId": "darkroom-free",
            "credits": 40,
            "isAnonymous": True,
            "lastSeenAt": datetime.now(UTC) - timedelta(days=90),
        }
    )
    removed = await reap_anonymous_users(db)
    assert removed >= 1
    assert await db.user.find_unique(where={"id": stale.id}) is None


async def test_reaping_spares_anonymous_accounts_with_work(db: Any) -> None:
    """An anonymous visitor who made something has content worth keeping."""
    kept = await db.user.create(
        data={
            "planId": "darkroom-free",
            "credits": 40,
            "isAnonymous": True,
            "lastSeenAt": datetime.now(UTC) - timedelta(days=90),
        }
    )
    await db.asset.create(
        data={
            "userId": kept.id,
            "mode": "IMAGE",
            "status": "READY",
            "prompt": "keep me",
            "composedPrompt": "keep me",
            "modelId": "halide-2",
            "ratioId": "1:1",
            "seed": 3,
            "width": 832,
            "height": 832,
            "creditCost": 2,
            "authorHandle": "anon",
        }
    )
    await reap_anonymous_users(db)
    assert await db.user.find_unique(where={"id": kept.id}) is not None
    await db.user.delete(where={"id": kept.id})


async def test_reaping_spares_claimed_accounts(db: Any) -> None:
    import uuid

    handle = f"kept.{uuid.uuid4().hex[:8]}"
    named = await db.user.create(
        data={
            "planId": "darkroom-free",
            "isAnonymous": False,
            "handle": handle,
            "handleLower": handle,
            "lastSeenAt": datetime.now(UTC) - timedelta(days=365),
        }
    )
    await reap_anonymous_users(db)
    assert await db.user.find_unique(where={"id": named.id}) is not None
    await db.user.delete(where={"id": named.id})


# ── monthly refresh ─────────────────────────────────────────────────────


async def test_refresh_tops_up_to_the_plan_allowance(db: Any, user: Any) -> None:
    # Spend down through the ledger. Writing `credits` directly would create
    # the drift this job exists to detect, and the assertion below would fail
    # for the wrong reason.
    await credit.grant(
        db, user_id=user.id, amount=-35, reason="ADMIN_ADJUSTMENT", note="spend"
    )
    await db.user.update(
        where={"id": user.id},
        data={"creditsResetAt": datetime.now(UTC) - timedelta(days=45)},
    )
    assert await refresh_monthly_credits(db) >= 1

    after = await db.user.find_unique(where={"id": user.id})
    assert after.credits == 40, "topped up to the allowance, not beyond it"
    # And the change is in the ledger, so reconciliation still holds.
    rows = await db.ledgerentry.find_many(
        where={"userId": user.id, "reason": "MONTHLY_REFRESH"}
    )
    assert len(rows) == 1 and rows[0].delta == 35
    assert not [d for d in await reconcile_ledger(db) if d.user_id == str(user.id)]


async def test_refresh_does_not_compound_unused_credits(
    db: Any, studio_user: Any
) -> None:
    """The allowance is a ceiling. Adding it every month would make an idle
    account richer than an active one."""
    await credit.grant(
        db, user_id=studio_user.id, amount=700, reason="PLAN_GRANT", note="topped"
    )
    await db.user.update(
        where={"id": studio_user.id},
        data={"creditsResetAt": datetime.now(UTC) - timedelta(days=45)},
    )
    await refresh_monthly_credits(db)
    after = await db.user.find_unique(where={"id": studio_user.id})
    assert after.credits == 1200


async def test_refresh_is_not_repeated_within_the_period(db: Any, user: Any) -> None:
    await credit.grant(
        db, user_id=user.id, amount=-35, reason="ADMIN_ADJUSTMENT", note="spend"
    )
    await db.user.update(
        where={"id": user.id},
        data={"creditsResetAt": datetime.now(UTC) - timedelta(days=45)},
    )
    await refresh_monthly_credits(db)
    first = (await db.user.find_unique(where={"id": user.id})).credits

    await credit.grant(
        db, user_id=user.id, amount=-35, reason="ADMIN_ADJUSTMENT", note="spend again"
    )
    await refresh_monthly_credits(db)
    assert (await db.user.find_unique(where={"id": user.id})).credits == 5, (
        "the reset stamp must gate a second top-up inside the same period"
    )
    assert first == 40
