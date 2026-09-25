"""Parameters to a generated frame. The swap point for a real backend.

Images are real: a keyless diffusion endpoint, chosen so a live link works for
a stranger with no API key and cannot drain one key when a hundred people open
it at once.

Motion is a real job producing a real generated keyframe, played under the
camera move the preset asks for. The frame is generated; the move is rendered
in the browser. Wiring a frame-by-frame video model is a change inside
`fetch_frame` and nothing above it.

Nothing here ever fetches a client-supplied URL. The upstream URL is built from
catalog rows plus validated parameters, which is what closes the SSRF door.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import httpx
import structlog

from app.config import get_settings
from app.core.breaker import CircuitBreaker
from app.core.errors import UpstreamFailed
from app.core.throttle import UpstreamBucket

log = structlog.get_logger(__name__)

ENGINE_PARAM = {"FLUX": "flux", "TURBO": "turbo", "KONTEXT": "kontext"}
MAX_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class FrameRequest:
    composed_prompt: str
    width: int
    height: int
    seed: int
    engine: str


def upstream_url(req: FrameRequest) -> str:
    s = get_settings()
    qs = urlencode(
        {
            "width": req.width,
            "height": req.height,
            "seed": req.seed,
            "model": ENGINE_PARAM.get(req.engine, "flux"),
            "nologo": "true",
            "referrer": "darkroom",
        }
    )
    return f"{s.upstream_base_url}{quote(req.composed_prompt, safe='')}?{qs}"


async def _await_token(bucket: UpstreamBucket, *, max_waits: int = 20) -> None:
    """Block until the global bucket grants a token.

    Waiting for a token is not a failed attempt, so it must not consume one of
    the retries -- that is a separate budget for upstream errors.
    """
    for _ in range(max_waits):
        wait = await bucket.take()
        if wait <= 0:
            return
        await asyncio.sleep(min(wait, 5.0))
    raise UpstreamFailed("Timed out waiting for upstream capacity.")


async def fetch_frame(
    req: FrameRequest,
    client: httpx.AsyncClient,
    bucket: UpstreamBucket,
    breaker: CircuitBreaker | None = None,
) -> bytes:
    """Fetch one frame, pacing against the global token bucket.

    Backoff uses full jitter: without it a thousand failed jobs retry in
    lockstep and reproduce the outage they are recovering from.
    """
    s = get_settings()
    url = upstream_url(req)
    last: str = "unavailable"

    # An open breaker means the upstream is down and retrying is what is
    # keeping it down. Refuse without attempting.
    if breaker is not None and not await breaker.allows():
        raise UpstreamFailed("The generator is unavailable; not retrying yet.")

    for attempt in range(MAX_ATTEMPTS):
        await _await_token(bucket)
        try:
            res = await client.get(
                url,
                headers={"accept": "image/*"},
                timeout=s.upstream_timeout_seconds,
                follow_redirects=True,
            )
            if res.status_code == 200 and res.content:
                if breaker is not None:
                    await breaker.record_success()
                return res.content
            last = str(res.status_code)
            # 503/429 mean "slow down", so slowing down is the whole remedy.
            if res.status_code in (429, 503):
                await asyncio.sleep(random.uniform(0, 2.5 * (attempt + 1)))  # noqa: S311
                continue
            break
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = type(exc).__name__
            await asyncio.sleep(random.uniform(0, 1.5 * (attempt + 1)))  # noqa: S311

    if breaker is not None:
        await breaker.record_failure()
    log.warning("generation.upstream_failed", status=last, seed=req.seed)
    raise UpstreamFailed(f"The generator answered {last}.")
