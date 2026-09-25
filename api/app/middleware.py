"""Middleware, written as pure ASGI rather than BaseHTTPMiddleware.

That is not a style preference. `BaseHTTPMiddleware` reads the response body
through an internal queue, which works for a finite response and deadlocks on an
endless one -- so `GET /v1/jobs/stream` returned 200 and then delivered nothing,
forever. Pure ASGI middleware passes `send` straight through, so a streaming
response streams.

Order is the order a request is processed in, outermost first:

    RequestIdMiddleware      every log line and every problem document needs it
    AccessLogMiddleware      logs outcomes, including the ones we reject
    GZipMiddleware           (Starlette's; skips text/event-stream by content)
    CORSMiddleware           a rejected preflight must not count against a limit
    RateLimitMiddleware      after identity is known, before any work is done
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import CONTENT_TYPE, RateLimited
from app.core.ratelimit import RateLimiter

log = structlog.get_logger(__name__)

# Route class -> limiter class. Anything unlisted defaults to `read`.
_CLASS_BY_PREFIX: list[tuple[str, str, str]] = [
    ("POST", "/v1/auth", "auth"),
    ("POST", "/v1/jobs", "write"),  # cancel and other job sub-resources
    ("PATCH", "/v1", "write"),
    ("PUT", "/v1", "write"),
    ("DELETE", "/v1", "write"),
]
EXEMPT = ("/v1/health", "/docs", "/openapi.json", "/redoc")

# A long-lived stream holds a connection, not a request budget. Counting it
# against `read` would let three reconnects lock a user out of the API.
STREAM_PATHS = ("/v1/jobs/stream",)


def classify(request: Request) -> str:
    """Pick the limiter class for a request.

    Only submitting a job is `generate`. Matching that class by prefix would make
    POST /v1/jobs/{id}/cancel spend generation budget, which is exactly
    backwards: cancelling is how a user stops spending.
    """
    path, method = request.url.path.rstrip("/"), request.method
    if method == "POST" and path == "/v1/jobs":
        return "generate"
    if method == "POST" and path == "/v1/jobs/quote":
        return "read"  # pure arithmetic over cached catalog rows
    for m, prefix, klass in _CLASS_BY_PREFIX:
        if method == m and path.startswith(prefix):
            return klass
    if request.query_params.get("q"):
        return "search"
    return "read"


class RequestIdMiddleware:
    """One id per request, in the response and in every log line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = Headers(scope=scope).get("x-request-id") or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("X-Request-Id", rid)
            await send(message)

        structlog.contextvars.bind_contextvars(request_id=rid)
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")


class AccessLogMiddleware:
    """One line per request, logged when the response starts.

    Logged at `http.response.start`, not at completion: a stream never completes,
    and a request that is never logged is a request nobody can debug.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        logged = False

        async def send_wrapper(message: Message) -> None:
            nonlocal logged
            if message["type"] == "http.response.start" and not logged:
                logged = True
                log.info(
                    "http.request",
                    method=scope.get("method"),
                    path=scope.get("path"),
                    status=message["status"],
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    user_id=scope.get("state", {}).get("user_id"),
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RateLimitMiddleware:
    """Sliding-window limiting, keyed on the caller.

    Denials are returned as problem+json from here rather than raised: middleware
    sits outside the exception-handler stack, so a raised DarkroomError escapes as
    an unhandled 500.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path.startswith(EXEMPT)
            or path in STREAM_PATHS
        ):
            await self.app(scope, receive, send)
            return

        from app.core.security import ACCESS_COOKIE, hash_ip, read_access_token
        from app.db import redis

        identity: str | None = None
        plan_id = "darkroom-free"
        token = request.cookies.get(ACCESS_COOKIE)
        if token:
            try:
                identity = read_access_token(token)["sub"]
            except Exception:
                identity = None
        if identity is None:
            client = request.client.host if request.client else None
            ua = request.headers.get("user-agent", "")[:120]
            identity = f"anon:{hash_ip(f'{client}|{ua}')}"

        scope.setdefault("state", {})["rate_identity"] = identity

        try:
            limiter = RateLimiter(redis())
        except RuntimeError:  # no Redis connected (unit tests)
            await self.app(scope, receive, send)
            return

        decision = await limiter.check(
            identity=identity, klass=classify(request), plan_id=plan_id
        )
        if not decision.allowed:
            exc = RateLimited(retry_after=decision.reset_seconds)
            rid = scope.get("state", {}).get("request_id", "-")
            response: Any = JSONResponse(
                status_code=exc.status,
                content=exc.problem(path, rid),
                media_type=CONTENT_TYPE,
                headers=decision.headers(),
            )
            await response(scope, receive, send)
            return

        headers = decision.headers()

        async def send_wrapper(message: Message) -> None:
            # Emitted on success too, so a well-behaved client can back off
            # before it is told to.
            if message["type"] == "http.response.start":
                out = MutableHeaders(scope=message)
                for k, v in headers.items():
                    out.append(k, v)
            await send(message)

        await self.app(scope, receive, send_wrapper)
