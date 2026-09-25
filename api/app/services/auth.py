"""Anonymous-first accounts.

A stranger gets a real User row, not an absence of one. That is what keeps
"signed out still works" true while making credits enforceable. Claiming a
handle upgrades the same row, so work made while anonymous stays attached.
"""

from __future__ import annotations

import uuid
from typing import Any

from prisma import Prisma
from prisma.enums import LedgerReason
from prisma.errors import UniqueViolationError

from app.config import get_settings
from app.core.errors import Conflict, NotFound, Unauthorized
from app.core.sanitize import normalize_handle
from app.core.security import hash_ip, hash_token, new_token
from app.repositories.users import UserRepository
from app.services import credit

DEFAULT_PLAN = "darkroom-free"


class AuthService:
    def __init__(self, db: Prisma) -> None:
        self._db = db
        self._users = UserRepository(db)

    async def create_anonymous(
        self, *, user_agent: str | None, ip: str | None
    ) -> tuple[Any, str]:
        s = get_settings()
        user = await self._users.create_anonymous(DEFAULT_PLAN, 0)
        await credit.grant(
            self._db,
            user_id=user.id,
            amount=s.anon_signup_credits,
            reason=LedgerReason.SIGNUP_GRANT,
            note="welcome",
        )
        refresh = await self._issue_refresh(user.id, None, user_agent, ip)
        fresh = await self._users.by_id(user.id)
        assert fresh is not None
        return fresh, refresh

    async def _issue_refresh(
        self,
        user_id: str,
        family_id: str | None,
        user_agent: str | None,
        ip: str | None,
    ) -> str:
        token = new_token()
        await self._users.create_session(
            user_id=user_id,
            token_hash=hash_token(token),
            family_id=family_id or str(uuid.uuid4()),
            ttl_seconds=get_settings().refresh_token_ttl_seconds,
            user_agent=user_agent,
            ip_hash=hash_ip(ip),
        )
        return token

    async def refresh(
        self, token: str, *, user_agent: str | None, ip: str | None
    ) -> tuple[Any, str]:
        """Rotate on use, with reuse detection.

        A second use of a consumed token revokes the whole family, so a stolen
        refresh token is good for one request rather than thirty days.
        """
        session = await self._users.session_by_hash(hash_token(token))
        if session is None:
            raise Unauthorized("That session is not valid.")
        if session.revokedAt is not None:
            await self._users.revoke_family(str(session.familyId))
            raise Unauthorized("That session was already used. Sign in again.")

        from datetime import UTC, datetime

        if session.expiresAt.replace(tzinfo=UTC) < datetime.now(UTC):
            raise Unauthorized("That session expired.")

        await self._users.revoke_session(str(session.id))
        user = await self._users.by_id(str(session.userId))
        if user is None:
            raise Unauthorized("That account no longer exists.")
        new_refresh = await self._issue_refresh(
            str(session.userId), str(session.familyId), user_agent, ip
        )
        return user, new_refresh

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        session = await self._users.session_by_hash(hash_token(token))
        if session is not None:
            await self._users.revoke_family(str(session.familyId))

    async def claim(self, user_id: str, raw_handle: str) -> Any:
        try:
            lower = normalize_handle(raw_handle)
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        existing = await self._users.by_handle(lower)
        if existing is not None and str(existing.id) != str(user_id):
            raise Conflict("That handle is taken.")
        try:
            return await self._users.claim_handle(user_id, raw_handle.strip(), lower)
        except UniqueViolationError as exc:
            raise Conflict("That handle is taken.") from exc

    async def set_plan(self, user_id: str, plan_id: str) -> Any:
        """Demo billing: plans switch without a payment.

        Real billing is a Stripe webhook writing PLAN_GRANT ledger entries. The
        ledger is already shaped for it; the payment is not built.
        """
        plan = await self._db.plan.find_unique(where={"id": plan_id})
        if plan is None or not plan.active:
            raise NotFound("No such plan.")
        user = await self._users.set_plan(user_id, plan_id)
        await credit.grant(
            self._db,
            user_id=user_id,
            amount=plan.monthlyCredits,
            reason=LedgerReason.PLAN_GRANT,
            note=f"switched to {plan.name}",
        )
        fresh = await self._users.by_id(user_id)
        return fresh or user
