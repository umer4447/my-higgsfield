"""Enqueue side of the job queue. Kept separate from the worker so the API
process does not import worker dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

STREAM_CHANNEL = "events:jobs"
QUEUE_KEY = "queue:generate"


async def enqueue_generate(redis: Redis, job_id: str) -> None:
    await redis.rpush(QUEUE_KEY, job_id)  # type: ignore[misc]


async def publish_event(
    redis: Redis, user_id: str, event: str, payload: dict[str, object]
) -> None:
    """Fan out a job transition to any SSE stream this user has open."""
    import json

    await redis.publish(
        f"{STREAM_CHANNEL}:{user_id}",
        json.dumps({"event": event, "data": payload}, default=str),
    )
