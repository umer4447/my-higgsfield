"""Dependency injection. Everything injectable is overridable in tests;
module-level globals are not."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Cookie, Depends, Header, Query, Request
from prisma import Prisma
from redis.asyncio import Redis

from app.core.errors import BadRequest, Unauthorized
from app.core.pagination import Cursor, clamp_limit, decode_cursor
from app.core.security import ACCESS_COOKIE, read_access_token
from app.db import db as _db
from app.db import redis as _redis
from app.repositories.users import UserRepository


def get_db() -> Prisma:
    return _db()


def get_redis() -> Redis:
    return _redis()


DB = Annotated[Prisma, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]


async def current_user(
    request: Request,
    db: DB,
    dr_at: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> Any:
    if not dr_at:
        raise Unauthorized("No session. Call /v1/auth/anonymous first.")
    payload = read_access_token(dr_at)
    user = await UserRepository(db).by_id(payload["sub"])
    if user is None:
        raise Unauthorized("That account no longer exists.")
    request.state.user_id = str(user.id)
    return user


async def optional_user(
    request: Request,
    db: DB,
    dr_at: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> Any | None:
    if not dr_at:
        return None
    try:
        payload = read_access_token(dr_at)
    except Unauthorized:
        return None
    user = await UserRepository(db).by_id(payload["sub"])
    if user is not None:
        request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[Any, Depends(current_user)]
OptionalUser = Annotated[Any, Depends(optional_user)]


class Pagination:
    def __init__(
        self,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
        limit: Annotated[int | None, Query(ge=1, le=60)] = None,
    ) -> None:
        self.cursor: Cursor | None = decode_cursor(cursor) if cursor else None
        self.limit: int = clamp_limit(limit)


PageParams = Annotated[Pagination, Depends(Pagination)]


def idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    """Required on anything that spends credits.

    A fresh key per submission intent, held across retries of that submission.
    A new key per retry defeats the whole mechanism.
    """
    if not idempotency_key:
        raise BadRequest("This endpoint requires an Idempotency-Key header.")
    if not 8 <= len(idempotency_key) <= 128:
        raise BadRequest("Idempotency-Key must be 8 to 128 characters.")
    return idempotency_key


IdempotencyKey = Annotated[str, Depends(idempotency_key)]
