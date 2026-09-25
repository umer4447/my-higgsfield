from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import InvalidCursor
from app.core.pagination import (
    MAX_LIMIT,
    build_page,
    clamp_limit,
    decode_cursor,
    encode_cursor,
)


def test_cursor_round_trips() -> None:
    ts = datetime.now(UTC)
    c = decode_cursor(encode_cursor(ts, "abc-123"))
    assert c.id == "abc-123"
    assert abs((c.ts - ts).total_seconds()) < 0.001


def test_forged_cursor_is_rejected() -> None:
    """A client that can forge a cursor can hand us a key that defeats the
    index, so a bad signature is a 400 rather than a query."""
    good = encode_cursor(datetime.now(UTC), "abc")
    body, _, _ = good.partition(".")
    for bad in ["tampered.signature", f"{body}.wrongsig", "", "nodot", body]:
        with pytest.raises(InvalidCursor):
            decode_cursor(bad)


def test_tampered_payload_behind_valid_shape_is_rejected() -> None:
    import base64
    import json

    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"v": 1, "t": "2026-01-01T00:00:00+00:00", "i": "x"}).encode()
        )
        .decode()
        .rstrip("=")
    )
    with pytest.raises(InvalidCursor):
        decode_cursor(f"{payload}.aaaaaaaaaaaaaaaaaaaaaa")


def test_limit_is_clamped() -> None:
    assert clamp_limit(None) == 24
    assert clamp_limit(1000) == MAX_LIMIT
    assert clamp_limit(0) == 1
    assert clamp_limit(30) == 30


class _Row:
    def __init__(self, i: int) -> None:
        self.id = f"row-{i:03d}"
        self.createdAt = datetime.now(UTC) - timedelta(minutes=i)


def test_extra_row_signals_has_more_without_a_count() -> None:
    """limit+1 answers hasMore for free; COUNT(*) would be a second scan."""
    page = build_page([_Row(i) for i in range(11)], 10, ts_field="createdAt")
    assert page.has_more is True
    assert len(page.data) == 10
    assert page.next_cursor is not None


def test_last_page_has_no_cursor() -> None:
    page = build_page([_Row(i) for i in range(4)], 10, ts_field="createdAt")
    assert page.has_more is False
    assert page.next_cursor is None


def test_empty_page() -> None:
    page = build_page([], 10, ts_field="createdAt")
    assert page.data == [] and page.has_more is False and page.next_cursor is None
