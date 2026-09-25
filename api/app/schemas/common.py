"""Shared Pydantic base and response envelopes."""

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    """Every request and response model inherits this.

    `extra="forbid"` matters: silently ignoring an unknown field turns a client
    typo into a mystery bug instead of a 422.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        alias_generator=to_camel,
        populate_by_name=True,
        # Pydantic reserves the `model_` prefix and this codebase is full of
        # `model_id` fields -- "model" is the domain noun for a generator.
        protected_namespaces=(),
    )


class PageMeta(Base):
    next_cursor: str | None = None
    has_more: bool = False
    limit: int


class PageResponse[T](Base):
    data: list[T]
    meta: PageMeta


def envelope(
    rows: list[Any], *, next_cursor: str | None, has_more: bool, limit: int
) -> dict[str, Any]:
    return {
        "data": rows,
        "meta": {"nextCursor": next_cursor, "hasMore": has_more, "limit": limit},
    }
