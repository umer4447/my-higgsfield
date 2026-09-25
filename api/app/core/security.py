"""Tokens, hashing, cookies.

Refresh tokens are stored hashed: a database dump must not be a set of working
credentials. Nothing goes in localStorage; cookies are httpOnly so injected
script cannot read them.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt

from app.config import get_settings
from app.core.errors import Unauthorized

ACCESS_COOKIE = "dr_at"
REFRESH_COOKIE = "dr_rt"
# A readable marker so the client knows a session exists without reading the
# httpOnly cookies. It carries no secret and grants nothing: its only job is to
# stop every first page load provoking a 401 on /v1/me.
SESSION_HINT_COOKIE = "dr_session"
_ALG = "HS256"


def new_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """SHA-256 hex. Tokens are high-entropy random, so a slow KDF buys nothing."""
    return hashlib.sha256(token.encode()).hexdigest()


def hash_ip(ip: str | None) -> str | None:
    """Salted hash. We need a stable rate-limit identity, not an address."""
    if not ip:
        return None
    salt = get_settings().ip_hash_salt.get_secret_value().encode()
    return hmac.new(salt, ip.encode(), hashlib.sha256).hexdigest()


def issue_access_token(user_id: str, *, anonymous: bool) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "anon": anonymous,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=s.access_token_ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=_ALG)


def read_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            get_settings().jwt_secret.get_secret_value(),
            algorithms=[_ALG],
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Your session expired. Refresh and try again.") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("That session token is not valid.") from exc


def cookie_kwargs(kind: Literal["access", "refresh", "hint"]) -> dict[str, Any]:
    s = get_settings()
    ttl = (
        s.access_token_ttl_seconds if kind == "access" else s.refresh_token_ttl_seconds
    )
    return {
        # The hint is deliberately readable; the tokens never are.
        "httponly": kind != "hint",
        "secure": s.is_prod,
        "samesite": "lax",
        "path": "/",
        "max_age": ttl,
    }


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
