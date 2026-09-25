"""Job submission and readback.

Constraints live on the types, not in validators, so they appear in the OpenAPI
document and in the generated client. Rules that need a database read (does
this preset exist, does this plan allow motion) belong in the service.
"""

from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from app.core.sanitize import sanitize_prompt
from app.schemas.common import Base

Prompt = Annotated[str, StringConstraints(min_length=3, max_length=2000)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{2,64}$")]
RatioId = Annotated[str, StringConstraints(pattern=r"^\d{1,2}:\d{1,2}$")]
# The global ceiling, matching CHECK (batch BETWEEN 1 AND 8) in migration
# 0002. The real limits are per-model (GenerationModel.maxBatch) and per-plan
# (Plan.maxBatch) and are enforced in the service, because they are data. A
# plan cap hardcoded here would make a paid plan unable to use a model batch
# size it is advertised as having.
Batch = Annotated[int, Field(ge=1, le=8)]
Seed = Annotated[int, Field(ge=0, le=9_999_999)]


class QuoteIn(Base):
    model_id: Slug
    batch: Batch = 1
    preset_slug: Slug | None = None


class QuoteOut(Base):
    base: int
    move_surcharge: int
    total: int
    credit_cost_per_output: int
    affordable: bool
    credits_available: int


class SubmitJobIn(Base):
    prompt: Prompt
    model_id: Slug
    ratio_id: RatioId
    preset_slug: Slug | None = None
    batch: Batch = 1
    seed: Seed | None = None

    @field_validator("prompt")
    @classmethod
    def _clean(cls, v: str) -> str:
        try:
            return sanitize_prompt(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class OutputOut(Base):
    id: str
    status: str
    seed: int
    width: int
    height: int
    url: str | None = None
    error: str | None = None


class JobOut(Base):
    id: str
    status: str
    mode: str
    prompt: str
    composed_prompt: str
    model_id: str
    preset_slug: str | None
    ratio_id: str
    batch: int
    move: str | None
    credits_debited: int
    credits_refunded: int
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    outputs: list[OutputOut]
