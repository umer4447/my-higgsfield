"""Server-sent events for the job tray.

Driven against the ASGI app directly rather than through httpx:
`httpx.ASGITransport` collects a response body before handing it back, so it
cannot observe a stream at all. That is a limitation of the test client, not of
the endpoint -- the Playwright suite exercises the same route over real HTTP
through uvicorn, which is the end-to-end proof.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.workers.queue import publish_event


class SSEClient:
    """Minimal SSE reader that speaks ASGI to the app under test."""

    def __init__(self, app: Any, cookies: str) -> None:
        self._app = app
        self._cookies = cookies
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self._buffer = ""
        self._frames: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> SSEClient:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "path": "/v1/jobs/stream",
            "raw_path": b"/v1/jobs/stream",
            "query_string": b"",
            "root_path": "",
            "scheme": "http",
            "headers": [(b"host", b"test"), (b"cookie", self._cookies.encode())],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "state": {},
        }

        async def receive() -> dict[str, str]:
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.status = message["status"]
                self.headers = {
                    k.decode().lower(): v.decode() for k, v in message["headers"]
                }
            elif message["type"] == "http.response.body":
                self._feed(message.get("body", b"").decode())

        self._task = asyncio.create_task(self._app(scope, receive, send))
        # Let the response start before assertions read status.
        for _ in range(50):
            if self.status is not None:
                break
            await asyncio.sleep(0.02)
        return self

    def _feed(self, chunk: str) -> None:
        self._buffer += chunk
        while "\n\n" in self._buffer:
            raw, self._buffer = self._buffer.split("\n\n", 1)
            frame: dict[str, str] = {}
            for line in raw.splitlines():
                if line.startswith("event:"):
                    frame["event"] = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    frame["data"] = line.split(":", 1)[1].strip()
            if frame.get("event"):
                self._frames.put_nowait(frame)

    async def next_event(self, deadline: float = 5.0) -> dict[str, str]:
        return await asyncio.wait_for(self._frames.get(), timeout=deadline)

    async def __aexit__(self, *_: object) -> None:
        if self._task is not None:
            self._task.cancel()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await self._task


async def _cookie_header(client: Any) -> str:
    await client.post("/v1/auth/anonymous")
    return "; ".join(f"{k}={v}" for k, v in client.cookies.items())


async def test_stream_requires_a_session(client: Any) -> None:
    async with client.stream("GET", "/v1/jobs/stream") as r:
        assert r.status_code == 401


async def test_stream_opens_with_a_ready_event(client: Any, app: Any) -> None:
    cookies = await _cookie_header(client)
    async with SSEClient(app, cookies) as sse:
        assert sse.status == 200
        assert sse.headers["content-type"].startswith("text/event-stream")
        assert sse.headers["cache-control"] == "no-store"
        # Proxies buffer text/event-stream unless told not to.
        assert sse.headers.get("x-accel-buffering") == "no"
        first = await sse.next_event()
        assert first["event"] == "ready"


async def test_stream_delivers_a_published_job_event(
    client: Any, app: Any, redis_client: Any
) -> None:
    """The worker publishes to a per-user channel; the open stream receives it."""
    me = (await client.post("/v1/auth/anonymous")).json()
    cookies = "; ".join(f"{k}={v}" for k, v in client.cookies.items())

    async with SSEClient(app, cookies) as sse:
        assert (await sse.next_event())["event"] == "ready"
        await asyncio.sleep(0.2)  # let the subscribe land
        await publish_event(
            redis_client, me["id"], "job.updated", {"id": "abc", "status": "running"}
        )
        event = await sse.next_event()

    assert event["event"] == "job.updated"
    assert json.loads(event["data"]) == {"id": "abc", "status": "running"}


async def test_events_are_scoped_to_one_user(
    client: Any, app: Any, redis_client: Any
) -> None:
    """An event for someone else must never arrive on my stream."""
    me = (await client.post("/v1/auth/anonymous")).json()
    cookies = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
    other = "00000000-0000-4000-8000-0000000000ff"

    async with SSEClient(app, cookies) as sse:
        assert (await sse.next_event())["event"] == "ready"
        await asyncio.sleep(0.2)
        await publish_event(redis_client, other, "job.updated", {"id": "theirs"})
        await publish_event(redis_client, me["id"], "job.updated", {"id": "mine"})
        event = await sse.next_event()

    assert json.loads(event["data"]) == {"id": "mine"}


async def test_output_ready_and_credits_events_reach_the_stream(
    client: Any, app: Any, redis_client: Any
) -> None:
    """The three event kinds the tray renders."""
    me = (await client.post("/v1/auth/anonymous")).json()
    cookies = "; ".join(f"{k}={v}" for k, v in client.cookies.items())

    async with SSEClient(app, cookies) as sse:
        assert (await sse.next_event())["event"] == "ready"
        await asyncio.sleep(0.2)
        for name, payload in [
            ("output.ready", {"jobId": "j1", "assetId": "a1"}),
            ("output.failed", {"jobId": "j1", "assetId": "a2"}),
            ("credits.changed", {"jobId": "j1"}),
        ]:
            await publish_event(redis_client, me["id"], name, payload)
        seen = [(await sse.next_event())["event"] for _ in range(3)]

    assert seen == ["output.ready", "output.failed", "credits.changed"]


async def test_stream_is_not_rate_limited_as_a_read(client: Any, app: Any) -> None:
    """A long-lived connection is not a request budget; reconnecting must not
    lock the caller out of the rest of the API."""
    from app.middleware import STREAM_PATHS

    assert "/v1/jobs/stream" in STREAM_PATHS
    cookies = await _cookie_header(client)
    for _ in range(4):
        async with SSEClient(app, cookies) as sse:
            assert sse.status == 200
    assert (await client.get("/v1/wall?limit=1")).status_code == 200
