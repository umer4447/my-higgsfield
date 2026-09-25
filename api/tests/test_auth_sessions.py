"""Refresh-token rotation and reuse detection.

The most security-sensitive code in the service: a stolen refresh token must be
good for one request, not thirty days.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.security import ACCESS_COOKIE, REFRESH_COOKIE, hash_token


async def test_anonymous_sets_both_cookies_httponly(client: Any) -> None:
    r = await client.post("/v1/auth/anonymous")
    assert r.status_code == 201
    jar = {c.name: c for c in client.cookies.jar}
    assert ACCESS_COOKIE in jar and REFRESH_COOKIE in jar
    # httpOnly is the whole reason nothing lives in localStorage.
    raw = " ".join(r.headers.get_list("set-cookie")).lower()
    # The two token cookies are httpOnly; the readable marker is not, and must
    # never be, or it could not do its job.
    assert raw.count("httponly") == 2, raw
    assert "dr_session=1" in raw
    # The marker must stay readable or it cannot do its job.
    hint_line = next(
        line for line in r.headers.get_list("set-cookie") if "dr_session" in line
    )
    assert "httponly" not in hint_line.lower(), hint_line


async def test_refresh_rotates_the_token(client: Any) -> None:
    await client.post("/v1/auth/anonymous")
    first = client.cookies.get(REFRESH_COOKIE)

    r = await client.post("/v1/auth/refresh")
    assert r.status_code == 200
    second = client.cookies.get(REFRESH_COOKIE)
    assert second and second != first, "the refresh token must rotate on use"


async def test_refresh_keeps_the_same_account(client: Any) -> None:
    before = (await client.post("/v1/auth/anonymous")).json()
    after = (await client.post("/v1/auth/refresh")).json()
    assert after["id"] == before["id"]
    assert after["credits"] == before["credits"]


async def test_replaying_a_consumed_token_revokes_the_family(
    client: Any, db: Any
) -> None:
    """Reuse detection. A second use of a spent token kills every session in
    the family, because the only way it can happen is that someone else has a
    copy."""
    me = (await client.post("/v1/auth/anonymous")).json()
    stolen = client.cookies.get(REFRESH_COOKIE)

    # The legitimate holder refreshes; `stolen` is now spent.
    assert (await client.post("/v1/auth/refresh")).status_code == 200
    live = client.cookies.get(REFRESH_COOKIE)

    # The attacker replays the spent token.
    client.cookies.set(REFRESH_COOKIE, stolen)
    replay = await client.post("/v1/auth/refresh")
    assert replay.status_code == 401
    assert "already used" in replay.json()["detail"]

    # And the legitimate session is dead too, which is the point.
    client.cookies.set(REFRESH_COOKIE, live)
    assert (await client.post("/v1/auth/refresh")).status_code == 401

    sessions = await db.session.find_many(where={"userId": me["id"]})
    assert sessions and all(s.revokedAt is not None for s in sessions)


async def test_expired_token_is_refused(client: Any, db: Any) -> None:
    await client.post("/v1/auth/anonymous")
    token = client.cookies.get(REFRESH_COOKIE)
    await db.session.update(
        where={"tokenHash": hash_token(token)},
        data={"expiresAt": datetime.now(UTC) - timedelta(days=1)},
    )
    r = await client.post("/v1/auth/refresh")
    assert r.status_code == 401
    assert "expired" in r.json()["detail"]


async def test_unknown_token_is_refused(client: Any) -> None:
    await client.post("/v1/auth/anonymous")
    client.cookies.set(REFRESH_COOKIE, "not-a-token-we-ever-issued")
    assert (await client.post("/v1/auth/refresh")).status_code == 401


async def test_refresh_without_a_cookie_is_401(client: Any) -> None:
    assert (await client.post("/v1/auth/refresh")).status_code == 401


async def test_tokens_are_stored_hashed_never_in_plaintext(
    client: Any, db: Any
) -> None:
    """A database dump must not be a set of working credentials."""
    await client.post("/v1/auth/anonymous")
    token = client.cookies.get(REFRESH_COOKIE)
    rows = await db.session.find_many(where={"tokenHash": hash_token(token)})
    assert len(rows) == 1
    assert rows[0].tokenHash != token
    assert len(rows[0].tokenHash) == 64
    # And the raw token appears nowhere in the table.
    assert not await db.session.find_first(where={"tokenHash": token})


async def test_logout_revokes_the_family(client: Any, db: Any) -> None:
    me = (await client.post("/v1/auth/anonymous")).json()
    assert (await client.post("/v1/auth/logout")).status_code == 204
    sessions = await db.session.find_many(where={"userId": me["id"]})
    assert all(s.revokedAt is not None for s in sessions)


async def test_ip_is_stored_hashed_not_raw(client: Any, db: Any) -> None:
    """Rate-limit identity, not an address: raw IPs are personal data."""
    me = (await client.post("/v1/auth/anonymous")).json()
    session = await db.session.find_first(where={"userId": me["id"]})
    assert session is not None
    if session.ipHash is not None:
        assert len(session.ipHash) == 64
        assert "." not in session.ipHash and ":" not in session.ipHash
