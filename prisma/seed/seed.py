"""Seed the catalog and the wall.

Idempotent: every write is an upsert keyed on the natural key, so this is safe
to run repeatedly against a database with real data.

It also validates. A preset whose template lacks {prompt} fails the seed loudly
rather than shipping a preset that silently discards what the user typed --
the database CHECK would reject it anyway, but a clear message beats a
constraint violation.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

from prisma import Prisma  # noqa: E402

from app.config import get_settings  # noqa: E402

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parents[1]
BAKED_WALL = REPO_ROOT / "public" / "wall"
CATALOG = json.loads((SEED_DIR / "catalog.json").read_text())
WALL = json.loads((SEED_DIR / "wall.json").read_text())

SEED_AUTHOR_PLAN = "darkroom-free"
FAMILY = {"Camera": "CAMERA", "Light": "LIGHT", "Stock": "STOCK", "World": "WORLD"}
ENGINE = {"flux": "FLUX", "turbo": "TURBO", "kontext": "KONTEXT"}


def _mode(v: str) -> str:
    return "MOTION" if v == "motion" else "IMAGE"


def _move(v: str | None) -> str | None:
    return v.upper() if v else None


def validate() -> None:
    problems: list[str] = []
    for p in CATALOG["presets"]:
        if "{prompt}" not in p["template"]:
            problems.append(f"preset {p['slug']}: template has no {{prompt}} slot")
        if p["family"] not in FAMILY:
            problems.append(f"preset {p['slug']}: unknown family {p['family']}")
    for m in CATALOG["models"]:
        if m["engine"] not in ENGINE:
            problems.append(f"model {m['id']}: unknown engine {m['engine']}")
        if m["cost"] < 1:
            problems.append(f"model {m['id']}: cost must be at least 1 credit")
    known_models = {m["id"] for m in CATALOG["models"]}
    known_presets = {p["slug"] for p in CATALOG["presets"]}
    known_ratios = {r["id"] for r in CATALOG["ratios"]}
    for w in WALL:
        if w["model"] not in known_models:
            problems.append(f"wall {w['seed']}: unknown model {w['model']}")
        if w.get("preset") and w["preset"] not in known_presets:
            problems.append(f"wall {w['seed']}: unknown preset {w['preset']}")
        if w["ratio"] not in known_ratios:
            problems.append(f"wall {w['seed']}: unknown ratio {w['ratio']}")
    if problems:
        for p in problems:
            print(f"  seed invalid: {p}", file=sys.stderr)
        raise SystemExit(1)


async def seed_catalog(db: Prisma) -> None:
    for i, p in enumerate(CATALOG["plans"]):
        data = {
            "id": p["id"],
            "name": p["name"],
            "tagline": p["tagline"],
            "priceCents": int(p["price"]) * 100,
            "monthlyCredits": p["credits"],
            "maxBatch": 4 if p["id"] == "darkroom-free" else 8,
            "maxConcurrentJobs": {"darkroom-free": 1, "darkroom-studio": 6}.get(p["id"], 12),
            "generatePerMinute": {"darkroom-free": 6, "darkroom-studio": 30}.get(p["id"], 90),
            "motionEnabled": p["id"] != "darkroom-free",
            "perks": p["perks"],
            "featured": bool(p.get("featured")),
            "sortOrder": i,
        }
        await db.plan.upsert(
            where={"id": p["id"]}, data={"create": data, "update": data}
        )

    for i, m in enumerate(CATALOG["models"]):
        data = {
            "id": m["id"],
            "name": m["name"],
            "vendor": m["vendor"],
            "mode": _mode(m["mode"]),
            "engine": ENGINE[m["engine"]],
            "creditCost": m["cost"],
            "maxBatch": m["maxBatch"],
            "blurb": m["blurb"],
            "badge": m.get("badge"),
            "sortOrder": i,
        }
        await db.generationmodel.upsert(
            where={"id": m["id"]}, data={"create": data, "update": data}
        )

    for i, r in enumerate(CATALOG["ratios"]):
        data = {
            "id": r["id"], "label": r["label"], "width": r["w"],
            "height": r["h"], "note": r["note"], "sortOrder": i,
        }
        await db.ratio.upsert(
            where={"id": r["id"]}, data={"create": data, "update": data}
        )

    for i, p in enumerate(CATALOG["presets"]):
        data = {
            "slug": p["slug"],
            "name": p["name"],
            "family": FAMILY[p["family"]],
            "mode": _mode(p["mode"]),
            "description": p["desc"],
            "template": p["template"],
            "move": _move(p.get("move")),
            "previewPrompt": p["previewPrompt"],
            "previewSeed": p["previewSeed"],
            "sortOrder": i,
        }
        await db.preset.upsert(
            where={"slug": p["slug"]}, data={"create": data, "update": data}
        )


async def seed_wall(db: Prisma) -> None:
    """The wall's starting content, as real parameters rather than stock images.

    Seeded assets belong to a system user so that ownership, publishing and the
    feed query all work exactly as they do for a real person.
    """
    from app.core.sanitize import compose_prompt

    system = await db.user.find_first(where={"handleLower": "darkroom.seed"})
    if system is None:
        system = await db.user.create(
            data={
                "planId": SEED_AUTHOR_PLAN,
                "handle": "darkroom.seed",
                "handleLower": "darkroom.seed",
                "isAnonymous": False,
                "credits": 0,
            }
        )

    models = {m["id"]: m for m in CATALOG["models"]}
    presets = {p["slug"]: p for p in CATALOG["presets"]}
    ratios = {r["id"]: r for r in CATALOG["ratios"]}

    from datetime import UTC, datetime, timedelta

    from app.services import storage

    store = storage.get_storage()
    base_time = datetime.now(UTC)

    for i, w in enumerate(WALL):
        model, ratio = models[w["model"]], ratios[w["ratio"]]
        preset = presets.get(w.get("preset") or "")
        asset_id = f"00000000-0000-4000-8000-{i:012d}"
        published_at = base_time - timedelta(minutes=i * 7)

        # Import the pre-baked frame into content-addressed storage, so the wall
        # works on a cold install with no upstream calls at all. The bytes go
        # through the same sniff-and-hash path as a generated frame, which means
        # a corrupt file fails the seed rather than serving a broken tile.
        storage_key: str | None = None
        digest: str | None = None
        size: int | None = None
        baked = BAKED_WALL / f"wall-{i:02d}.jpg"
        if baked.is_file():
            data = baked.read_bytes()
            ext = storage.sniff(data)
            digest = storage.content_hash(data)
            storage_key = storage.key_for(digest, ext)
            size = len(data)
            if not store.exists(storage_key):
                store.put(storage_key, data)
        data = {
            "id": asset_id,
            "userId": system.id,
            "mode": _mode(model["mode"]),
            "prompt": w["prompt"],
            "composedPrompt": compose_prompt(
                w["prompt"], preset["template"] if preset else None
            ),
            "modelId": w["model"],
            "presetSlug": w.get("preset"),
            "ratioId": w["ratio"],
            "seed": w["seed"],
            "move": _move(w.get("move") or (preset or {}).get("move")),
            "width": ratio["w"],
            "height": ratio["h"],
            "creditCost": model["cost"],
            "authorHandle": w["author"],
            "published": True,
            "publishedAt": published_at,
            "likeCount": w["likes"],
            "seeded": True,
            # No baked file means the frame is not there yet; PENDING is honest
            # and the worker can fill it later rather than serving a 404.
            "status": "READY" if storage_key else "PENDING",
            "storageKey": storage_key,
            "contentHash": digest,
            "bytes": size,
        }
        await db.asset.upsert(
            where={"id": asset_id}, data={"create": data, "update": data}
        )


async def main() -> None:
    validate()
    settings = get_settings()
    db = Prisma(datasource={"url": settings.database_url})
    await db.connect()
    try:
        await seed_catalog(db)
        await seed_wall(db)
        counts = {
            "plans": await db.plan.count(),
            "models": await db.generationmodel.count(),
            "ratios": await db.ratio.count(),
            "presets": await db.preset.count(),
            "wall assets": await db.asset.count(where={"seeded": True}),
            "with frames": await db.asset.count(
                where={"seeded": True, "status": "READY"}
            ),
        }
        print("seeded: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
