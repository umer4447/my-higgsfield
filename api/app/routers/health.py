"""Two health endpoints, not one.

A load balancer that removes an instance because the database is briefly slow
makes an outage worse, so liveness checks the process and readiness checks the
dependencies.
"""

from fastapi import APIRouter, Response

from app.deps import DB, RedisDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(db: DB, redis: RedisDep, response: Response) -> dict[str, object]:
    checks: dict[str, object] = {}
    try:
        await db.query_raw("SELECT 1 AS ok")
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"

    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", "checks": checks}
