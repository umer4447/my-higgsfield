"""Structured JSON logs. One line per request.

Prompts are never logged at info level: they are user content. Tokens, cookies
and raw IPs are never logged at all.
"""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_REDACT = {"password", "token", "secret", "cookie", "authorization", "prompt"}


def _redact(
    _: Any, __: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for k in list(event):
        if k.lower() in _REDACT:
            event[k] = "<redacted>"
    return event


def configure(*, json_output: bool = True) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
