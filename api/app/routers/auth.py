from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Request, Response

from app.config import get_settings
from app.core.security import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    SESSION_HINT_COOKIE,
    cookie_kwargs,
    issue_access_token,
)
from app.deps import DB, CurrentUser
from app.schemas.auth import ClaimIn
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(response: Response, user: Any, refresh: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        issue_access_token(str(user.id), anonymous=user.isAnonymous),
        **cookie_kwargs("access"),
    )
    response.set_cookie(REFRESH_COOKIE, refresh, **cookie_kwargs("refresh"))
    response.set_cookie(SESSION_HINT_COOKIE, "1", **cookie_kwargs("hint"))


def _me(user: Any, jobs_in_flight: int = 0) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "handle": user.handle,
        "isAnonymous": user.isAnonymous,
        "credits": user.credits,
        "planId": user.planId,
        "planName": user.plan.name if user.plan else user.planId,
        "maxConcurrentJobs": user.plan.maxConcurrentJobs if user.plan else 1,
        "jobsInFlight": jobs_in_flight,
        "motionEnabled": user.plan.motionEnabled if user.plan else False,
        "createdAt": user.createdAt,
    }


@router.post("/anonymous", status_code=201)
async def anonymous(request: Request, response: Response, db: DB) -> dict[str, Any]:
    """A stranger gets a real account and the signup grant.

    This is what keeps the composer working signed out while making credits
    enforceable on the server.
    """
    user, refresh = await AuthService(db).create_anonymous(
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    _set_cookies(response, user, refresh)
    return _me(user)


@router.post("/claim")
async def claim(
    body: ClaimIn, response: Response, db: DB, user: CurrentUser
) -> dict[str, Any]:
    """Upgrade the same row, so work made while anonymous stays attached."""
    updated = await AuthService(db).claim(str(user.id), body.handle)
    response.set_cookie(
        ACCESS_COOKIE,
        issue_access_token(str(updated.id), anonymous=False),
        **cookie_kwargs("access"),
    )
    return _me(updated)


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: DB,
    dr_rt: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> dict[str, Any]:
    from app.core.errors import Unauthorized

    if not dr_rt:
        raise Unauthorized("No refresh token.")
    user, new_refresh = await AuthService(db).refresh(
        dr_rt,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    _set_cookies(response, user, new_refresh)
    return _me(user)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    db: DB,
    dr_rt: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> Response:
    await AuthService(db).logout(dr_rt)
    settings = get_settings()
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, SESSION_HINT_COOKIE):
        response.delete_cookie(name, path="/", secure=settings.is_prod, samesite="lax")
    return Response(status_code=204)
