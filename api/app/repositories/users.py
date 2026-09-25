from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prisma import Prisma
from prisma.models import Session, User


class UserRepository:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def by_id(self, user_id: str) -> User | None:
        return await self._db.user.find_first(
            where={"id": user_id, "deletedAt": None}, include={"plan": True}
        )

    async def by_handle(self, handle_lower: str) -> User | None:
        return await self._db.user.find_unique(where={"handleLower": handle_lower})

    async def create_anonymous(self, plan_id: str, initial_credits: int) -> User:
        return await self._db.user.create(
            data={"planId": plan_id, "credits": initial_credits, "isAnonymous": True},
            include={"plan": True},
        )

    async def claim_handle(self, user_id: str, handle: str, handle_lower: str) -> User:
        updated = await self._db.user.update(
            where={"id": user_id},
            data={"handle": handle, "handleLower": handle_lower, "isAnonymous": False},
            include={"plan": True},
        )
        if updated is None:
            raise ValueError(f"user {user_id} disappeared during claim")
        return updated

    async def set_plan(self, user_id: str, plan_id: str) -> User:
        # Relations update through connect, not by writing the scalar FK.
        updated = await self._db.user.update(
            where={"id": user_id},
            data={"plan": {"connect": {"id": plan_id}}},
            include={"plan": True},
        )
        if updated is None:
            raise ValueError(f"user {user_id} disappeared during plan change")
        return updated

    async def touch(self, user_id: str) -> None:
        await self._db.user.update(
            where={"id": user_id}, data={"lastSeenAt": datetime.now(UTC)}
        )

    # ── sessions ────────────────────────────────────────────────────────

    async def create_session(
        self,
        *,
        user_id: str,
        token_hash: str,
        family_id: str,
        ttl_seconds: int,
        user_agent: str | None,
        ip_hash: str | None,
    ) -> Session:
        return await self._db.session.create(
            data={
                "userId": user_id,
                "tokenHash": token_hash,
                "familyId": family_id,
                "userAgent": (user_agent or "")[:400] or None,
                "ipHash": ip_hash,
                "expiresAt": datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            }
        )

    async def session_by_hash(self, token_hash: str) -> Session | None:
        return await self._db.session.find_unique(where={"tokenHash": token_hash})

    async def revoke_session(self, session_id: str) -> None:
        await self._db.session.update(
            where={"id": session_id}, data={"revokedAt": datetime.now(UTC)}
        )

    async def revoke_family(self, family_id: str) -> None:
        """Reuse detection: a replayed refresh token kills the whole family."""
        await self._db.session.update_many(
            where={"familyId": family_id, "revokedAt": None},
            data={"revokedAt": datetime.now(UTC)},
        )
