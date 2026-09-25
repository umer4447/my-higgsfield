from datetime import datetime
from typing import Annotated

from pydantic import StringConstraints

from app.schemas.common import Base

RawHandle = Annotated[str, StringConstraints(min_length=3, max_length=32)]


class ClaimIn(Base):
    handle: RawHandle


class PlanIn(Base):
    plan_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{2,64}$")]


class MeOut(Base):
    id: str
    handle: str | None
    is_anonymous: bool
    credits: int
    plan_id: str
    plan_name: str
    max_concurrent_jobs: int
    jobs_in_flight: int
    motion_enabled: bool
    created_at: datetime


class LedgerRowOut(Base):
    id: str
    reason: str
    delta: int
    balance_after: int
    note: str | None
    job_id: str | None
    created_at: datetime
