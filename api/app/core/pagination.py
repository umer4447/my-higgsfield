"""Opaque, signed keyset cursors. See architecture.md section 8.

Offset pagination is wrong for a feed: OFFSET n walks and discards n rows, and
rows arriving at the top make page 2 re-show items from page 1. The cursor is
the last row's sort key, so cost is constant in page depth.

Cursors are HMAC-signed because a client that can forge one can hand us a key
that defeats the index or leaks ordering internals.
"""

import base64
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from app.config import get_settings
from app.core.errors import InvalidCursor

DEFAULT_LIMIT = 24
MAX_LIMIT = 60
_VERSION = 1


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(body: str) -> str:
    secret = get_settings().cursor_secret.get_secret_value().encode()
    return _b64e(hmac.new(secret, body.encode(), sha256).digest()[:16])


@dataclass(frozen=True, slots=True)
class Cursor:
    ts: datetime
    id: str


def encode_cursor(ts: datetime | None, row_id: str) -> str:
    stamp = (ts or datetime.fromtimestamp(0, UTC)).astimezone(UTC).isoformat()
    body = _b64e(
        json.dumps(
            {"v": _VERSION, "t": stamp, "i": row_id}, separators=(",", ":")
        ).encode()
    )
    return f"{body}.{_sign(body)}"


def decode_cursor(cursor: str) -> Cursor:
    body, _, sig = cursor.partition(".")
    if not body or not sig or not hmac.compare_digest(sig, _sign(body)):
        raise InvalidCursor
    try:
        payload = json.loads(_b64d(body))
        if payload.get("v") != _VERSION:
            raise InvalidCursor
        return Cursor(ts=datetime.fromisoformat(payload["t"]), id=str(payload["i"]))
    except InvalidCursor:
        raise
    except Exception as exc:  # malformed payload behind a valid signature
        raise InvalidCursor from exc


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


@dataclass(slots=True)
class Page[T]:
    data: list[T]
    next_cursor: str | None
    has_more: bool

    def as_dict(self, limit: int, serialize: Any = None) -> dict[str, Any]:
        rows = [serialize(r) for r in self.data] if serialize else self.data
        return {
            "data": rows,
            "meta": {
                "nextCursor": self.next_cursor,
                "hasMore": self.has_more,
                "limit": limit,
            },
        }


def build_page(
    rows: list[Any],
    limit: int,
    *,
    ts_field: str,
    id_field: str = "id",
) -> Page[Any]:
    """Trim the limit+1 probe row and derive the next cursor.

    Fetching limit+1 answers hasMore for free; COUNT(*) would be a second scan
    of the filtered set.
    """
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            getattr(last, ts_field), str(getattr(last, id_field))
        )
    return Page(data=rows, next_cursor=next_cursor, has_more=has_more)
