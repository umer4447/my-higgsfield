"""The schema objects Prisma cannot express must actually exist.

This test is not paranoia. The Prisma migration runner stops executing a file
after CREATE EXTENSION without raising, so a migration can report success while
silently skipping every statement after it. The symptom is a missing index and
a query that quietly falls back to a sequential scan.
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

EXPECTED_CHECKS = {
    "users_credits_non_negative",
    "jobs_refund_within_debit",
    "jobs_batch_bounded",
    "presets_template_has_slot",
}

EXPECTED_INDEXES = {
    "assets_prompt_trgm_idx",
    "assets_published_publishedAt_id_idx",
    "assets_userId_createdAt_id_idx",
    "jobs_userId_createdAt_id_idx",
    "jobs_status_queuedAt_idx",
    "ledger_entries_userId_createdAt_id_idx",
}


async def test_check_constraints_exist(db: Any) -> None:
    rows = await db.query_raw(
        "SELECT conname FROM pg_constraint "
        "WHERE contype = 'c' AND connamespace = 'public'::regnamespace"
    )
    present = {r["conname"] for r in rows}
    missing = EXPECTED_CHECKS - present
    assert not missing, f"CHECK constraints absent from the database: {missing}"


async def test_indexes_exist(db: Any) -> None:
    rows = await db.query_raw(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
    )
    present = {r["indexname"] for r in rows}
    missing = EXPECTED_INDEXES - present
    assert not missing, f"indexes absent from the database: {missing}"


async def test_pg_trgm_is_installed(db: Any) -> None:
    rows = await db.query_raw(
        "SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'"
    )
    assert rows, "pg_trgm missing: the prompt search index cannot exist without it"


async def test_credits_check_is_enforced(db: Any, user: Any) -> None:
    from prisma.errors import PrismaError

    with pytest.raises(PrismaError):
        await db.execute_raw(
            'UPDATE "users" SET "credits" = -5 WHERE "id" = $1::uuid', str(user.id)
        )


async def test_preset_template_check_is_enforced(db: Any) -> None:
    from prisma.errors import PrismaError

    with pytest.raises(PrismaError):
        await db.execute_raw(
            'UPDATE "presets" SET "template" = \'no slot here\' WHERE "slug" = $1',
            "kodachrome-64",
        )


async def test_wall_feed_query_uses_an_index(db: Any, user: Any) -> None:
    """No sequential scan on the hottest query in the app.

    The planner is right to scan a nearly-empty table, so this asserts against
    volume: 20k published rows, ANALYZEd, which is the regime the index exists
    for. Without the row count the assertion passes or fails on table size
    rather than on whether the index is correct.
    """
    await db.execute_raw(
        """
        INSERT INTO "assets" (
            "id", "userId", "mode", "status", "prompt", "composedPrompt",
            "modelId", "ratioId", "seed", "width", "height", "creditCost",
            "authorHandle", "published", "publishedAt", "createdAt", "updatedAt"
        )
        SELECT gen_random_uuid(), $1::uuid, 'IMAGE', 'READY',
               'bench prompt ' || g, 'bench prompt ' || g,
               'halide-2', '1:1', g, 832, 832, 2, 'bench',
               true, now() - (g || ' seconds')::interval, now(), now()
        FROM generate_series(1, 20000) AS g
        """,
        str(user.id),
    )
    try:
        await db.execute_raw('ANALYZE "assets"')
        rows = await db.query_raw(
            'EXPLAIN SELECT "id" FROM "assets" '
            'WHERE "published" AND "deletedAt" IS NULL AND "status" = \'READY\' '
            'ORDER BY "publishedAt" DESC, "id" DESC LIMIT 25'
        )
        plan = " ".join(str(v) for r in rows for v in r.values())
        assert "Seq Scan" not in plan, plan
        # And no sort node: the index already supplies the ordering.
        assert "Sort" not in plan, plan
    finally:
        await db.execute_raw('DELETE FROM "assets" WHERE "authorHandle" = $1', "bench")
        await db.execute_raw('ANALYZE "assets"')


async def test_prompt_search_index_is_defined_correctly(db: Any) -> None:
    """The trigram index exists, is GIN, and uses gin_trgm_ops on prompt.

    Deliberately not an assertion about which plan Postgres picks. Whether the
    planner prefers this index over a scan depends on row counts, term
    selectivity and table bloat, all of which move between runs -- a cost
    decision is not a correctness property and makes a flaky test. What must be
    true is that the index exists and matches the `%` predicate.
    """
    rows = await db.query_raw(
        "SELECT indexdef FROM pg_indexes "
        "WHERE schemaname = 'public' AND indexname = 'assets_prompt_trgm_idx'"
    )
    assert rows, "assets_prompt_trgm_idx is missing"
    definition = rows[0]["indexdef"]
    assert "USING gin" in definition, definition
    assert "gin_trgm_ops" in definition, definition
    assert '"prompt"' in definition or "(prompt" in definition, definition


class _RollbackError(Exception):
    """Sentinel: unwinds the benchmark transaction without persisting rows."""


async def test_planner_can_use_the_trigram_index(db: Any, user: Any) -> None:
    """Given the choice, Postgres uses the trigram index for a `%` search.

    Run inside one transaction with sequential scans disabled, so the answer is
    about index eligibility rather than this run's table statistics. The whole
    transaction is rolled back, so no benchmark rows survive.
    """
    insert = """
        INSERT INTO "assets" (
            "id", "userId", "mode", "status", "prompt", "composedPrompt",
            "modelId", "ratioId", "seed", "width", "height", "creditCost",
            "authorHandle", "published", "publishedAt", "createdAt", "updatedAt"
        )
        SELECT gen_random_uuid(), $1::uuid, 'IMAGE', 'READY',
               CASE WHEN g % 2000 = 0 THEN 'bench lighthouse in fog ' || g
                    ELSE 'bench unrelated subject ' || g END,
               'bench composed ' || g,
               'halide-2', '1:1', g, 832, 832, 2, 'bench',
               true, now() - (g || ' seconds')::interval, now(), now()
        FROM generate_series(1, 20000) AS g
    """
    plan = ""
    with contextlib.suppress(_RollbackError):
        async with db.tx() as tx:
            await tx.execute_raw(insert, str(user.id))
            await tx.execute_raw("SET LOCAL enable_seqscan = off")
            rows = await tx.query_raw(
                'EXPLAIN SELECT "id" FROM "assets" WHERE "prompt" % $1', "lighthouse"
            )
            plan = " ".join(str(v) for r in rows for v in r.values())
            raise _RollbackError

    assert "assets_prompt_trgm_idx" in plan, plan

    remaining = await db.asset.count(where={"authorHandle": "bench"})
    assert remaining == 0, "the benchmark transaction must leave nothing behind"
