"""Test fixtures.

Real Postgres and real Redis. Never SQLite, never a mocked database: half this
design is CHECK constraints, partial indexes and transaction semantics, and a
mock tests none of it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

os.environ.setdefault("ENVIRONMENT", "test")
_TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://mrmacbook@localhost:5432/darkroom_test"
)
os.environ["DATABASE_URL"] = _TEST_DB
os.environ["DIRECT_DATABASE_URL"] = _TEST_DB
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-0000")
os.environ.setdefault("CURSOR_SECRET", "test-cursor-test-cursor-test-cursor-0000")
os.environ.setdefault("IP_HASH_SALT", "test-salt-test-salt-test-salt-test-00000")
os.environ.setdefault("STORAGE_LOCAL_DIR", "/tmp/darkroom-test-storage")  # noqa: S108


@pytest.fixture(scope="session", autouse=True)
def migrated() -> None:
    """Apply migrations and seed once, against the test database."""
    env = {**os.environ, "DATABASE_URL": _TEST_DB, "DIRECT_DATABASE_URL": _TEST_DB}
    subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "prisma",
            "migrate",
            "deploy",
            "--schema",
            str(ROOT / "prisma" / "schema.prisma"),
        ],
        check=True,
        env=env,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "prisma" / "seed" / "seed.py")],
        check=True,
        env=env,
        capture_output=True,
    )


@pytest.fixture
async def db() -> AsyncIterator[Any]:
    from prisma import Prisma

    client = Prisma(datasource={"url": _TEST_DB})
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
async def redis_client() -> AsyncIterator[Any]:
    from redis.asyncio import Redis

    r = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await r.flushdb()
    yield r
    await r.aclose()


async def _make_user(db: Any, plan_id: str, starting_credits: int) -> Any:
    """Create a user the way the application does: no balance, then a grant.

    Writing `credits` directly would put the row in drift the moment it exists,
    and the reconciliation job would be right to flag it.
    """
    from app.services import credit

    u = await db.user.create(data={"planId": plan_id}, include={"plan": True})
    if starting_credits:
        await credit.grant(
            db,
            user_id=u.id,
            amount=starting_credits,
            reason="SIGNUP_GRANT",
            note="fixture",
        )
    return await db.user.find_unique(where={"id": u.id}, include={"plan": True})


@pytest.fixture
async def user(db: Any) -> AsyncIterator[Any]:
    """A fresh free-plan user with 40 credits, removed afterwards."""
    u = await _make_user(db, "darkroom-free", 40)
    yield u
    await db.user.delete(where={"id": u.id})


@pytest.fixture
async def studio_user(db: Any) -> AsyncIterator[Any]:
    u = await _make_user(db, "darkroom-studio", 500)
    yield u
    await db.user.delete(where={"id": u.id})


@pytest.fixture
async def app(redis_client: Any) -> AsyncIterator[Any]:
    """The ASGI app with its lifespan running.

    Needed by the SSE tests, which speak ASGI directly because
    httpx.ASGITransport buffers response bodies and cannot observe a stream.
    """
    from app.main import create_app

    instance = create_app()
    async with instance.router.lifespan_context(instance):
        yield instance


@pytest.fixture
async def client(redis_client: Any) -> AsyncIterator[Any]:
    """ASGI client with a clean Redis, so limits do not leak between tests."""
    import httpx

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def make_job_body(**over: Any) -> dict[str, Any]:
    return {
        "prompt": "a lighthouse in dense fog at dawn",
        "modelId": "halide-2",
        "ratioId": "4:5",
        "batch": 1,
        **over,
    }


def key() -> str:
    return uuid.uuid4().hex
