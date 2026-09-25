from typing import Any

from fastapi import APIRouter

from app.core.pagination import build_page
from app.core.throttle import ConcurrencyThrottle
from app.deps import DB, CurrentUser, PageParams, RedisDep
from app.repositories.ledger import LedgerRepository
from app.routers.auth import _me
from app.schemas.auth import PlanIn
from app.services.auth import AuthService

router = APIRouter(tags=["me"])


@router.get("/me")
async def me(user: CurrentUser, redis: RedisDep) -> dict[str, Any]:
    in_flight = await ConcurrencyThrottle(redis).in_flight(str(user.id))
    return _me(user, jobs_in_flight=in_flight)


@router.patch("/me/plan")
async def set_plan(body: PlanIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    updated = await AuthService(db).set_plan(str(user.id), body.plan_id)
    return _me(updated)


@router.get("/ledger")
async def ledger(db: DB, user: CurrentUser, page: PageParams) -> dict[str, Any]:
    """Every credit debited and refunded, itemised. Keyset-paged."""
    rows = await LedgerRepository(db).page(
        str(user.id), cursor=page.cursor, limit=page.limit
    )
    result = build_page(rows, page.limit, ts_field="createdAt")
    return {
        "data": [
            {
                "id": str(r.id),
                "reason": r.reason.lower(),
                "delta": r.delta,
                "balanceAfter": r.balanceAfter,
                "note": r.note,
                "jobId": str(r.jobId) if r.jobId else None,
                "createdAt": r.createdAt,
            }
            for r in result.data
        ],
        "meta": {
            "nextCursor": result.next_cursor,
            "hasMore": result.has_more,
            "limit": page.limit,
        },
    }
