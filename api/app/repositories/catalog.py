"""Catalog reads. Cached in Redis by the service; these are the cold path."""

from __future__ import annotations

from typing import Any

from prisma import Prisma
from prisma.models import GenerationModel, Plan, Preset, Ratio


class CatalogRepository:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def models(self) -> list[GenerationModel]:
        return await self._db.generationmodel.find_many(
            where={"active": True}, order=[{"sortOrder": "asc"}, {"id": "asc"}]
        )

    async def presets(self) -> list[Preset]:
        return await self._db.preset.find_many(
            where={"active": True}, order=[{"sortOrder": "asc"}, {"slug": "asc"}]
        )

    async def ratios(self) -> list[Ratio]:
        return await self._db.ratio.find_many(
            where={"active": True}, order=[{"sortOrder": "asc"}, {"id": "asc"}]
        )

    async def plans(self) -> list[Plan]:
        return await self._db.plan.find_many(
            where={"active": True}, order=[{"sortOrder": "asc"}, {"id": "asc"}]
        )

    async def model(self, model_id: str) -> GenerationModel | None:
        return await self._db.generationmodel.find_unique(where={"id": model_id})

    async def preset(self, slug: str) -> Preset | None:
        return await self._db.preset.find_unique(where={"slug": slug})

    async def ratio(self, ratio_id: str) -> Ratio | None:
        return await self._db.ratio.find_unique(where={"id": ratio_id})

    async def plan(self, plan_id: str) -> Plan | None:
        return await self._db.plan.find_unique(where={"id": plan_id})

    async def as_payload(self) -> dict[str, Any]:
        models, presets, ratios, plans = (
            await self.models(),
            await self.presets(),
            await self.ratios(),
            await self.plans(),
        )
        return {
            "models": [m.model_dump(mode="json") for m in models],
            "presets": [p.model_dump(mode="json") for p in presets],
            "ratios": [r.model_dump(mode="json") for r in ratios],
            "plans": [p.model_dump(mode="json") for p in plans],
        }
