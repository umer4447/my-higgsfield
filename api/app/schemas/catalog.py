from app.schemas.common import Base


class ModelOut(Base):
    id: str
    name: str
    vendor: str
    mode: str
    engine: str
    credit_cost: int
    max_batch: int
    blurb: str
    badge: str | None = None


class PresetOut(Base):
    slug: str
    name: str
    family: str
    mode: str
    description: str
    template: str
    move: str | None = None
    preview_prompt: str
    preview_seed: int


class RatioOut(Base):
    id: str
    label: str
    width: int
    height: int
    note: str


class PlanOut(Base):
    id: str
    name: str
    tagline: str
    price_cents: int
    monthly_credits: int
    max_batch: int
    max_concurrent_jobs: int
    motion_enabled: bool
    perks: list[str]
    featured: bool


class CatalogOut(Base):
    models: list[ModelOut]
    presets: list[PresetOut]
    ratios: list[RatioOut]
    plans: list[PlanOut]
