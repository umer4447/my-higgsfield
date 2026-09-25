from __future__ import annotations

from typing import Any

from prisma import Prisma
from prisma.models import LedgerEntry
from prisma.types import LedgerEntryWhereInput


class LedgerRepository:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def page(self, user_id: str, *, cursor: Any, limit: int) -> list[LedgerEntry]:
        where: LedgerEntryWhereInput = {"userId": user_id}
        if cursor:
            where["OR"] = [
                {"createdAt": {"lt": cursor.ts}},
                {"createdAt": cursor.ts, "id": {"lt": int(cursor.id)}},
            ]
        return await self._db.ledgerentry.find_many(
            where=where,
            order=[{"createdAt": "desc"}, {"id": "desc"}],
            take=limit + 1,
        )

    async def balance_from_ledger(self, user_id: str) -> int:
        """The reconciliation invariant: this must equal users.credits."""
        rows = await self._db.query_raw(
            'SELECT COALESCE(SUM("delta"), 0)::int AS total '
            'FROM "ledger_entries" WHERE "userId" = $1::uuid',
            user_id,
        )
        return int(rows[0]["total"]) if rows else 0
