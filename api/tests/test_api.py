"""HTTP-level behaviour: auth, validation, ownership, idempotency, limits."""

from __future__ import annotations

from typing import Any

from tests.conftest import key, make_job_body


async def _session(client: Any) -> dict[str, Any]:
    r = await client.post("/v1/auth/anonymous")
    assert r.status_code == 201
    return r.json()


# ── catalog ─────────────────────────────────────────────────────────────


async def test_catalog_is_complete_and_etagged(client: Any) -> None:
    r = await client.get("/v1/catalog")
    assert r.status_code == 200
    body = r.json()
    assert len(body["models"]) == 5
    assert len(body["presets"]) == 18
    assert len(body["ratios"]) == 5
    assert len(body["plans"]) == 3
    etag = r.headers["etag"]
    again = await client.get("/v1/catalog", headers={"If-None-Match": etag})
    assert again.status_code == 304


async def test_every_preset_template_carries_the_prompt_slot(client: Any) -> None:
    body = (await client.get("/v1/catalog")).json()
    for p in body["presets"]:
        assert "{prompt}" in p["template"], p["slug"]


# ── auth ────────────────────────────────────────────────────────────────


async def test_anonymous_visitor_gets_a_real_account_and_credits(client: Any) -> None:
    """Signed out still works -- enforced on the server, not asserted on the
    client."""
    me = await _session(client)
    assert me["isAnonymous"] is True
    assert me["credits"] == 40
    assert me["planName"] == "Contact"


async def test_signup_grant_is_recorded_in_the_ledger(client: Any) -> None:
    await _session(client)
    rows = (await client.get("/v1/ledger")).json()["data"]
    assert [r["reason"] for r in rows] == ["signup_grant"]
    assert rows[0]["delta"] == 40
    assert rows[0]["balanceAfter"] == 40


async def test_protected_endpoints_require_a_session(client: Any) -> None:
    for path in ("/v1/me", "/v1/library", "/v1/ledger", "/v1/jobs"):
        r = await client.get(path)
        assert r.status_code == 401, path
        assert r.headers["content-type"].startswith("application/problem+json")


async def test_claiming_a_handle_keeps_the_same_account(client: Any) -> None:
    before = await _session(client)
    r = await client.post("/v1/auth/claim", json={"handle": f"tester{key()[:6]}"})
    assert r.status_code == 200
    after = r.json()
    assert after["id"] == before["id"], "claiming upgrades the row, not replaces it"
    assert after["isAnonymous"] is False
    assert after["credits"] == before["credits"]


async def test_reserved_handles_are_refused(client: Any) -> None:
    await _session(client)
    r = await client.post("/v1/auth/claim", json={"handle": "admin"})
    assert r.status_code == 409


# ── wall ────────────────────────────────────────────────────────────────


async def test_wall_shows_the_prompt_for_every_item(client: Any) -> None:
    """The product's first claim, asserted."""
    body = (await client.get("/v1/wall?limit=10")).json()
    assert len(body["data"]) == 10
    for item in body["data"]:
        assert item["prompt"]
        assert item["composedPrompt"]
        assert item["modelId"] and item["ratioId"] and item["seed"]


async def test_wall_pages_without_overlap(client: Any) -> None:
    p1 = (await client.get("/v1/wall?limit=5")).json()
    assert p1["meta"]["hasMore"] is True
    p2 = (
        await client.get(f"/v1/wall?limit=5&cursor={p1['meta']['nextCursor']}")
    ).json()
    ids1 = {a["id"] for a in p1["data"]}
    ids2 = {a["id"] for a in p2["data"]}
    assert not (ids1 & ids2), "keyset pages must not repeat rows"


async def test_forged_cursor_is_a_400_not_a_crash(client: Any) -> None:
    r = await client.get("/v1/wall?cursor=tampered.signature")
    assert r.status_code == 400
    assert r.json()["title"] == "Invalid cursor"


async def test_search_requires_two_characters(client: Any) -> None:
    assert (await client.get("/v1/wall?q=a")).status_code == 422
    assert (await client.get("/v1/wall?q=courier")).status_code == 200


async def test_limit_is_capped(client: Any) -> None:
    assert (await client.get("/v1/wall?limit=9999")).status_code == 422


async def test_batch_over_model_capacity_is_refused(client: Any) -> None:
    """plate generates at most 2 at a time; the model row is the authority."""
    await _session(client)
    r = await client.post(
        "/v1/jobs",
        json=make_job_body(modelId="plate", batch=4),
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 409
    assert "at most 2" in r.json()["detail"]


async def test_paid_plan_reaches_a_model_batch_the_free_plan_cannot(
    client: Any,
) -> None:
    """halide-flash generates 6 at a time. A free-plan cap baked into the wire
    schema would make that unreachable no matter what the user pays."""
    await _session(client)
    assert (
        await client.post(
            "/v1/jobs",
            json=make_job_body(modelId="halide-flash", batch=6),
            headers={"Idempotency-Key": key()},
        )
    ).status_code == 409  # free plan maxBatch is 4

    await client.patch("/v1/me/plan", json={"planId": "darkroom-studio"})
    r = await client.post(
        "/v1/jobs",
        json=make_job_body(modelId="halide-flash", batch=6),
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 201, r.json()
    assert len(r.json()["outputs"]) == 6


# ── quote ───────────────────────────────────────────────────────────────


async def test_quote_matches_what_is_charged(client: Any) -> None:
    """Cost before you spend: the quote and the debit share one function."""
    await _session(client)
    q = (
        await client.post("/v1/jobs/quote", json={"modelId": "halide-2", "batch": 2})
    ).json()
    assert q == {
        "base": 4,
        "moveSurcharge": 0,
        "total": 4,
        "creditCostPerOutput": 2,
        "affordable": True,
        "creditsAvailable": 40,
    }

    r = await client.post(
        "/v1/jobs", json=make_job_body(batch=2), headers={"Idempotency-Key": key()}
    )
    assert r.status_code == 201
    assert r.json()["creditsDebited"] == q["total"]


async def test_quote_includes_the_move_surcharge(client: Any) -> None:
    await _session(client)
    q = (
        await client.post(
            "/v1/jobs/quote",
            json={"modelId": "halide-2", "batch": 2, "presetSlug": "anamorphic-night"},
        )
    ).json()
    assert q["moveSurcharge"] == 2
    assert q["total"] == 6


# ── submit ──────────────────────────────────────────────────────────────


async def test_submit_requires_an_idempotency_key(client: Any) -> None:
    await _session(client)
    r = await client.post("/v1/jobs", json=make_job_body())
    assert r.status_code == 400


async def test_submit_debits_and_creates_outputs(client: Any) -> None:
    await _session(client)
    r = await client.post(
        "/v1/jobs", json=make_job_body(batch=2), headers={"Idempotency-Key": key()}
    )
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "queued"
    assert job["creditsDebited"] == 4
    assert len(job["outputs"]) == 2
    # Seeds resolved at submit, which is what makes Remix exact.
    assert all(o["seed"] > 0 for o in job["outputs"])
    assert (await client.get("/v1/me")).json()["credits"] == 36


async def test_same_key_replays_and_charges_once(client: Any) -> None:
    await _session(client)
    k, body = key(), make_job_body()
    first = await client.post("/v1/jobs", json=body, headers={"Idempotency-Key": k})
    second = await client.post("/v1/jobs", json=body, headers={"Idempotency-Key": k})
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers.get("idempotency-replayed") == "true"
    assert first.json()["id"] == second.json()["id"]
    assert (await client.get("/v1/me")).json()["credits"] == 38, "charged once"


async def test_same_key_different_body_is_refused(client: Any) -> None:
    """A client reusing a key for a different request has a bug; silently
    replaying the old response would hide it."""
    await _session(client)
    k = key()
    await client.post(
        "/v1/jobs", json=make_job_body(batch=1), headers={"Idempotency-Key": k}
    )
    r = await client.post(
        "/v1/jobs", json=make_job_body(batch=2), headers={"Idempotency-Key": k}
    )
    assert r.status_code == 409


async def test_a_still_accepts_a_motion_preset(client: Any) -> None:
    """A motion preset on a still is its look without the move, which the
    composer has always allowed -- the seeded wall is full of them."""
    await _session(client)
    r = await client.post(
        "/v1/jobs",
        json=make_job_body(modelId="halide-2", presetSlug="anamorphic-night"),
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 201, r.json()
    assert r.json()["presetSlug"] == "anamorphic-night"


async def test_motion_needs_a_preset_that_carries_a_move(client: Any) -> None:
    """The constrained direction: the move is the thing being rendered."""
    await _session(client)
    await client.patch("/v1/me/plan", json={"planId": "darkroom-studio"})
    r = await client.post(
        "/v1/jobs",
        json=make_job_body(
            modelId="reel-9", ratioId="16:9", presetSlug="kodachrome-64"
        ),
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 409
    assert "camera move" in r.json()["detail"]


async def test_motion_is_refused_on_the_free_plan(client: Any) -> None:
    await _session(client)
    r = await client.post(
        "/v1/jobs",
        json=make_job_body(modelId="reel-9", ratioId="16:9"),
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 409
    assert "Studio" in r.json()["detail"]
    assert (await client.get("/v1/me")).json()["credits"] == 40, "nothing charged"


async def test_unaffordable_job_is_refused_with_402(client: Any, db: Any) -> None:
    me = await _session(client)
    # Drop the balance directly rather than by spending: spending would trip
    # the free plan's one-job concurrency cap first and test the wrong thing.
    await db.user.update(where={"id": me["id"]}, data={"credits": 4})

    # halide-2 is 2 credits/output, maxBatch 4 -> 8 credits, against 4 held.
    r = await client.post(
        "/v1/jobs",
        json=make_job_body(modelId="halide-2", batch=4),
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 402
    body = r.json()
    assert body["required"] == 8 and body["available"] == 4
    assert (await client.get("/v1/me")).json()["credits"] == 4, "nothing charged"


async def test_validation_errors_name_the_field(client: Any) -> None:
    await _session(client)
    r = await client.post(
        "/v1/jobs", json=make_job_body(prompt="x"), headers={"Idempotency-Key": key()}
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "prompt"


async def test_unknown_field_is_rejected(client: Any) -> None:
    """extra=forbid: a client typo is a 422, not a silently ignored field."""
    await _session(client)
    r = await client.post(
        "/v1/jobs",
        json=make_job_body(presetSlugs="oops"),
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 422


# ── cancel and refund ───────────────────────────────────────────────────


async def test_cancel_refunds_in_full(client: Any) -> None:
    await _session(client)
    job = (
        await client.post(
            "/v1/jobs", json=make_job_body(batch=2), headers={"Idempotency-Key": key()}
        )
    ).json()
    assert (await client.get("/v1/me")).json()["credits"] == 36

    r = await client.post(f"/v1/jobs/{job['id']}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert r.json()["creditsRefunded"] == 4
    assert (await client.get("/v1/me")).json()["credits"] == 40


async def test_ledger_itemises_debit_and_refund(client: Any) -> None:
    await _session(client)
    job = (
        await client.post(
            "/v1/jobs", json=make_job_body(), headers={"Idempotency-Key": key()}
        )
    ).json()
    await client.post(f"/v1/jobs/{job['id']}/cancel")
    rows = (await client.get("/v1/ledger")).json()["data"]
    assert [r["reason"] for r in rows] == ["job_refund", "job_debit", "signup_grant"]
    assert sum(r["delta"] for r in rows) == 40


# ── ownership ───────────────────────────────────────────────────────────


async def test_another_user_gets_404_not_403(client: Any, db: Any) -> None:
    """404 rather than 403: a 403 confirms the id exists, which is an
    enumeration oracle."""
    await _session(client)
    job = (
        await client.post(
            "/v1/jobs", json=make_job_body(), headers={"Idempotency-Key": key()}
        )
    ).json()
    asset_id = job["outputs"][0]["id"]

    await client.post("/v1/auth/logout")
    await client.post("/v1/auth/anonymous")

    assert (await client.get(f"/v1/assets/{asset_id}")).status_code == 404
    assert (await client.get(f"/v1/jobs/{job['id']}")).status_code == 404
    assert (
        await client.patch(f"/v1/assets/{asset_id}", json={"published": True})
    ).status_code in (403, 404)


async def test_library_only_shows_your_own_work(client: Any) -> None:
    await _session(client)
    await client.post(
        "/v1/jobs", json=make_job_body(batch=2), headers={"Idempotency-Key": key()}
    )
    assert len((await client.get("/v1/library")).json()["data"]) == 2

    await client.post("/v1/auth/logout")
    await client.post("/v1/auth/anonymous")
    assert (await client.get("/v1/library")).json()["data"] == []


# ── rate limiting ───────────────────────────────────────────────────────


async def test_generate_limit_returns_429_with_retry_after(client: Any) -> None:
    """Free plan allows 6 generate calls a minute."""
    await _session(client)
    statuses = []
    for _ in range(9):
        r = await client.post(
            "/v1/jobs",
            json=make_job_body(modelId="halide-flash"),
            headers={"Idempotency-Key": key()},
        )
        statuses.append(r.status_code)
        if r.status_code == 429:
            assert r.headers["content-type"].startswith("application/problem+json")
            assert int(r.headers["Retry-After"]) >= 1
            assert r.json()["status"] == 429
            break
    assert 429 in statuses, "the generate class must be enforced"


async def test_cancel_does_not_consume_generate_budget(client: Any) -> None:
    """Cancelling is how a user stops spending; it must not be rate-limited as
    if it were spending."""
    await _session(client)
    # Submit-then-cancel five times. The free plan allows one job in flight, so
    # this also proves cancel releases the concurrency permit.
    for _ in range(5):
        r = await client.post(
            "/v1/jobs",
            json=make_job_body(modelId="halide-flash"),
            headers={"Idempotency-Key": key()},
        )
        assert r.status_code == 201, r.json()
        assert (
            await client.post(f"/v1/jobs/{r.json()['id']}/cancel")
        ).status_code == 200


async def test_rate_limit_headers_are_present_on_success(client: Any) -> None:
    await _session(client)
    r = await client.get("/v1/wall")
    assert "RateLimit-Limit" in r.headers
    assert "RateLimit-Remaining" in r.headers


# ── health and errors ───────────────────────────────────────────────────


async def test_health_endpoints(client: Any) -> None:
    assert (await client.get("/v1/health")).json() == {"status": "ok"}
    ready = await client.get("/v1/health/ready")
    assert ready.json()["checks"] == {"postgres": "ok", "redis": "ok"}


async def test_every_error_is_problem_json_with_a_request_id(client: Any) -> None:
    r = await client.get("/v1/me")
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    for field in ("type", "title", "status", "detail", "instance", "requestId"):
        assert field in body
    assert r.headers["X-Request-Id"] == body["requestId"]


async def test_free_plan_allows_one_job_in_flight(client: Any) -> None:
    """Throttling caps simultaneity, which rate limiting does not. A second
    concurrent job is refused with `concurrency`, not a generic slow-down."""
    await _session(client)
    first = await client.post(
        "/v1/jobs", json=make_job_body(), headers={"Idempotency-Key": key()}
    )
    assert first.status_code == 201

    second = await client.post(
        "/v1/jobs", json=make_job_body(), headers={"Idempotency-Key": key()}
    )
    assert second.status_code == 429
    assert second.json()["reason"] == "concurrency"
    # Refused after the debit, so the credits must come back.
    assert (await client.get("/v1/me")).json()["credits"] == 38

    await client.post(f"/v1/jobs/{first.json()['id']}/cancel")
    third = await client.post(
        "/v1/jobs", json=make_job_body(), headers={"Idempotency-Key": key()}
    )
    assert third.status_code == 201, "the permit is released on cancel"
