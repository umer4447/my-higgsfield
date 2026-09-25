"""RFC 9457 problem+json, and the domain exceptions that map onto it.

Services raise domain exceptions and never import fastapi. One handler turns
them into problem documents, which keeps status-code policy in a single file.
"""

from typing import Any

CONTENT_TYPE = "application/problem+json"
_BASE = "https://darkroom.dev/problems/"


class DarkroomError(Exception):
    """Base for everything the API deliberately returns to a client."""

    status: int = 500
    slug: str = "internal-error"
    title: str = "Something went wrong"

    def __init__(self, detail: str = "", **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra

    def problem(self, instance: str, request_id: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": f"{_BASE}{self.slug}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "instance": instance,
            "requestId": request_id,
        }
        body.update(self.extra)
        return body


class BadRequest(DarkroomError):
    status, slug, title = 400, "bad-request", "Bad request"


class InvalidCursor(BadRequest):
    slug, title = "invalid-cursor", "Invalid cursor"

    def __init__(self) -> None:
        super().__init__("That pagination cursor is not one we issued.")


class Unauthorized(DarkroomError):
    status, slug, title = 401, "unauthorized", "Not signed in"


class Forbidden(DarkroomError):
    status, slug, title = 403, "forbidden", "Not allowed"


class NotFound(DarkroomError):
    # Also used for another user's private resource: a 403 would confirm the
    # id exists, which is an enumeration oracle.
    status, slug, title = 404, "not-found", "Not found"


class Conflict(DarkroomError):
    status, slug, title = 409, "conflict", "Conflicting state"


class PreconditionFailed(DarkroomError):
    status, slug, title = 412, "precondition-failed", "The resource changed"


class InsufficientCredits(DarkroomError):
    status, slug, title = 402, "insufficient-credits", "Not enough credits"

    def __init__(self, required: int, available: int) -> None:
        super().__init__(
            f"That costs {required} credits and you have {available}.",
            required=required,
            available=available,
        )


class PlanForbids(Conflict):
    slug, title = "plan-forbids", "Your plan does not allow that"


class RateLimited(DarkroomError):
    status, slug, title = 429, "rate-limited", "Too many requests"

    def __init__(self, retry_after: int, reason: str = "rate") -> None:
        detail = (
            "Wait for one of your own jobs to finish."
            if reason == "concurrency"
            else "You are going faster than this endpoint allows."
        )
        super().__init__(detail, retryAfter=retry_after, reason=reason)
        self.retry_after = retry_after


class UpstreamFailed(DarkroomError):
    status, slug, title = 502, "upstream-failed", "The generator did not answer"


class QueueFull(DarkroomError):
    status, slug, title = 503, "queue-full", "The queue is full"

    def __init__(self, retry_after: int = 30) -> None:
        super().__init__(
            "Too much work in flight. Nothing was charged.", retryAfter=retry_after
        )
        self.retry_after = retry_after
