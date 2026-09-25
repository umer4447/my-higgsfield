from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from app.core.sanitize import sanitize_search
from app.schemas.common import Base

Search = Annotated[str, StringConstraints(min_length=2, max_length=100)]


class AssetOut(Base):
    id: str
    mode: str
    status: str
    prompt: str
    composed_prompt: str
    model_id: str
    preset_slug: str | None
    ratio_id: str
    seed: int
    move: str | None
    width: int
    height: int
    credit_cost: int
    author_handle: str
    published: bool
    like_count: int
    liked_by_me: bool = False
    seeded: bool
    url: str | None
    version: int
    created_at: datetime


class FeedQuery(Base):
    cursor: str | None = None
    limit: Annotated[int, Field(ge=1, le=60)] = 24
    mode: Annotated[str, StringConstraints(pattern=r"^(image|motion)$")] | None = None
    preset: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{2,64}$")] | None = (
        None
    )
    q: Search | None = None

    @field_validator("q")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return sanitize_search(v)


class LibraryQuery(FeedQuery):
    published: bool | None = None


class PublishIn(Base):
    published: bool
