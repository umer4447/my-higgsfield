"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.core import logging as log_config
from app.core.errors import CONTENT_TYPE, DarkroomError, RateLimited
from app.db import connect, disconnect
from app.middleware import AccessLogMiddleware, RateLimitMiddleware, RequestIdMiddleware
from app.routers import assets, auth, catalog, frames, health, jobs, me, wall

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Connect once at startup. Connection churn against a pooled Postgres turns
    # a 15ms endpoint into a 300ms one.
    await connect()
    log.info("api.started", environment=get_settings().environment)
    try:
        yield
    finally:
        await disconnect()


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DarkroomError)
    async def domain_error(request: Request, exc: DarkroomError) -> JSONResponse:
        headers: dict[str, str] = {}
        if isinstance(exc, RateLimited):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status,
            content=exc.problem(request.url.path, _request_id(request)),
            media_type=CONTENT_TYPE,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]),
                "message": e["msg"],
                "type": e["type"],
            }
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "type": "https://darkroom.dev/problems/validation-failed",
                "title": "That request did not validate",
                "status": 422,
                "detail": "One or more fields are missing or out of range.",
                "instance": request.url.path,
                "requestId": _request_id(request),
                "errors": errors,
            },
            media_type=CONTENT_TYPE,
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, _exc: Exception) -> JSONResponse:
        # Never leak internals. Log the detail with the id; return the id.
        log.error("api.unhandled", path=request.url.path, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "type": "https://darkroom.dev/problems/internal-error",
                "title": "Something went wrong",
                "status": 500,
                "detail": "An unexpected error occurred. Quote the request id.",
                "instance": request.url.path,
                "requestId": _request_id(request),
            },
            media_type=CONTENT_TYPE,
        )


def create_app() -> FastAPI:
    settings = get_settings()
    log_config.configure(json_output=settings.environment != "dev")

    app = FastAPI(
        title="Darkroom API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Outermost first: each wraps everything below it.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AccessLogMiddleware)
    # GZip compresses by size and leaves text/event-stream alone, but it still
    # wraps the response; keeping it above CORS and below the loggers means a
    # stream passes through untouched.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "idempotency-key", "if-match", "if-none-match"],
        expose_headers=[
            "X-Request-Id",
            "RateLimit-Limit",
            "RateLimit-Remaining",
            "RateLimit-Reset",
            "Retry-After",
            "ETag",
            "Idempotency-Replayed",
        ],
    )
    app.add_middleware(RateLimitMiddleware)

    for router in (
        health.router,
        catalog.router,
        auth.router,
        me.router,
        wall.router,
        assets.router,
        jobs.router,
        frames.router,
    ):
        app.include_router(router, prefix="/v1")

    register_exception_handlers(app)
    return app


app = create_app()


def main() -> Any:
    import uvicorn

    return uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)  # noqa: S104
