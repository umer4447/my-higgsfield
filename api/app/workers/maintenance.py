"""Scheduled maintenance. See architecture.md sections 6, 14 and 15.

Three jobs that the design depends on but that no request path can perform:

  - ledger reconciliation, which is the only thing that proves the money
    invariant holds in production rather than in a test
  - reaping abandoned anonymous users, without which the users table becomes a
    bot-traffic landfill
  - the monthly credit refresh that the plans advertise

Each is idempotent and safe to run concurrently with traffic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from prisma import Prisma

log = structlog.get_logger(__name__)

ANON_RETENTION_DAYS = 30
REFRESH_PERIOD_DAYS = 30


@dataclass(frozen=True, slots=True)
class Drift:
    user_id: str
    credits: int
    ledger_sum: int

    @property
    def delta(self) -> int:
        return self.credits - self.ledger_sum


async def reconcile_ledger(db: Prisma, *, limit: int = 1000) -> list[Drift]:
    """Assert users.credits == SUM(ledger.delta) for every account.

    The materialised balance is a denormalisation of the ledger. If they ever
    disagree, one of them is lying about money, and we need to know within a day
    rather than when a user complains. Non-empty result pages an operator.
    """
    rows = await db.query_raw(
        """
        SELECT u."id"::text AS user_id,
               u."credits" AS credits,
               COALESCE(SUM(l."delta"), 0)::int AS ledger_sum
          FROM "users" u
          LEFT JOIN "ledger_entries" l ON l."userId" = u."id"
         GROUP BY u."id", u."credits"
        HAVING u."credits" <> COALESCE(SUM(l."delta"), 0)::int
         LIMIT $1
        """,
        limit,
    )
    drift = [
        Drift(
            user_id=r["user_id"],
            credits=int(r["credits"]),
            ledger_sum=int(r["ledger_sum"]),
        )
        for r in rows
    ]
    if drift:
        # This is money. It is the one alert that pages immediately.
        log.error(
            "ledger.drift_detected",
            count=len(drift),
            worst=max(abs(d.delta) for d in drift),
            user_ids=[d.user_id for d in drift[:10]],
        )
    else:
        log.info("ledger.reconciled", drift=0)
    return drift


async def reap_anonymous_users(
    db: Prisma, *, older_than_days: int = ANON_RETENTION_DAYS
) -> int:
    """Delete anonymous accounts with no work and no recent activity.

    Only accounts that own nothing: an anonymous visitor who generated
    something has content worth keeping, and deleting it would cascade their
    assets away. Cascades handle sessions and ledger rows.
    """
    # Naive UTC: the columns are `timestamp without time zone`, and a raw
    # parameter arrives as text, so the cast below needs no offset.
    cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).replace(tzinfo=None)
    rows = await db.query_raw(
        """
        DELETE FROM "users" u
         WHERE u."isAnonymous"
           AND u."lastSeenAt" < $1::timestamp
           AND NOT EXISTS (SELECT 1 FROM "assets" a WHERE a."userId" = u."id")
           AND NOT EXISTS (SELECT 1 FROM "jobs" j WHERE j."userId" = u."id")
        RETURNING u."id"::text AS id
        """,
        cutoff,
    )
    if rows:
        log.info("users.reaped", count=len(rows))
    return len(rows)


async def refresh_monthly_credits(db: Prisma, *, batch: int = 500) -> int:
    """Top accounts back up to their plan allowance, once per period.

    Tops up rather than adds: the allowance is a ceiling, so an unused balance
    does not compound into free credits. Every change is a ledger entry, so the
    reconciliation above still holds afterwards.
    """
    now = datetime.now(UTC)
    naive_cutoff = (now - timedelta(days=REFRESH_PERIOD_DAYS)).replace(tzinfo=None)
    due = await db.query_raw(
        """
        SELECT u."id"::text AS id,
               u."credits" AS credits,
               p."monthlyCredits" AS allowance
          FROM "users" u
          JOIN "plans" p ON p."id" = u."planId"
         WHERE u."deletedAt" IS NULL
           AND (u."creditsResetAt" IS NULL OR u."creditsResetAt" < $1::timestamp)
           AND u."credits" < p."monthlyCredits"
         LIMIT $2
        """,
        naive_cutoff,
        batch,
    )

    from app.services import credit

    refreshed = 0
    for row in due:
        top_up = int(row["allowance"]) - int(row["credits"])
        if top_up <= 0:
            continue
        await credit.grant(
            db,
            user_id=row["id"],
            amount=top_up,
            reason="MONTHLY_REFRESH",  # type: ignore[arg-type]
            note="monthly allowance",
        )
        await db.user.update(where={"id": row["id"]}, data={"creditsResetAt": now})
        refreshed += 1
    if refreshed:
        log.info("credits.refreshed", count=refreshed)
    return refreshed


async def run_all(db: Prisma) -> dict[str, int]:
    """One pass. Called on a schedule by the worker."""
    drift = await reconcile_ledger(db)
    return {
        "drift": len(drift),
        "reaped": await reap_anonymous_users(db),
        "refreshed": await refresh_monthly_credits(db),
    }
