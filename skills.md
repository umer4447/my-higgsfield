# skills.md — Darkroom engineering playbooks

Working reference for the Darkroom backend. Companion to
[`architecture.md`](architecture.md), which says *what* we built and *why*; this
file says *how* to write the next piece of it so it matches.

Every recipe here is copy-adaptable and reflects a decision already taken. If a
recipe and the architecture disagree, the architecture wins and this file is the
bug.

**Contents**

1. [FastAPI service conventions](#1-fastapi-service-conventions)
2. [Pydantic v2 validation](#2-pydantic-v2-validation)
3. [Prisma schema and migrations](#3-prisma-schema-and-migrations)
4. [Query patterns](#4-query-patterns)
5. [Transactions and the money path](#5-transactions-and-the-money-path)
6. [Idempotency](#6-idempotency)
7. [Pagination](#7-pagination)
8. [Rate limiting and throttling](#8-rate-limiting-and-throttling)
9. [Sanitization and injection defence](#9-sanitization-and-injection-defence)
10. [Errors](#10-errors)
11. [Background work](#11-background-work)
12. [Frontend contract](#12-frontend-contract)
13. [Testing](#13-testing)
14. [Observability](#14-observability)
15. [Lint, types, CI](#15-lint-types-ci)
16. [Anti-patterns](#16-anti-patterns)

---

## 1. FastAPI service conventions

**Layering.** `routers → services → repositories → prisma`. Enforced by
`import-linter`; a violation fails CI.

| Layer | May import | Must not | Responsibility |
|---|---|---|---|
| `routers/` | services, schemas, deps | prisma, repositories | HTTP: parse, authorise, serialise, status codes |
| `services/` | repositories, core | fastapi, prisma | Business rules. The only layer with policy |
| `repositories/` | prisma | fastapi, services | Every query. One method per query |
| `core/` | stdlib, redis | services, routers | Cross-cutting: security, limits, cursors, errors |

The payoff is concrete: services are testable without an HTTP client, and
swapping Prisma Client Python for SQLAlchemy touches `repositories/` only.

**App factory.** Middleware order is not cosmetic — it is the order a request is
processed in, and getting it wrong means logging requests you rejected or
rate-limiting requests you cannot identify.

```python
# api/app/main.py
def create_app() -> FastAPI:
    app = FastAPI(
        title="Darkroom API", version="1.0.0",
        default_response_class=ORJSONResponse,   # 2-3x faster than stdlib json
        lifespan=lifespan,
    )
    # OUTERMOST FIRST. Each wraps everything below it.
    app.add_middleware(RequestIdMiddleware)      # 1. every log line needs this
    app.add_middleware(AccessLogMiddleware)      # 2. log outcomes, incl. 429s
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(CORSMiddleware, **cors_config())
    app.add_middleware(RateLimitMiddleware)      # 5. after identity, before work
    app.include_router(v1_router, prefix="/v1")
    register_exception_handlers(app)             # problem+json, always
    return app
```

`RateLimitMiddleware` sits below CORS so a rejected preflight is not counted, and
below logging so denials appear in the access log — a 429 you cannot see is a
support ticket you cannot answer.

**Lifespan, not `@on_event`.** Connect Prisma and Redis once at startup; never
per request. Connection churn against a pooled Postgres is the fastest way to
turn a 15 ms endpoint into a 300 ms one.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = Prisma()
    await app.state.db.connect()
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.db.disconnect()
```

**Never block the event loop.** One synchronous `requests.get` or `time.sleep` in
an `async def` stalls every concurrent request on that worker. Ruff's `ASYNC`
rules catch the common cases; for genuinely CPU-bound work (image header decode,
sha256 of a large buffer) use `await anyio.to_thread.run_sync(fn, arg)`.

**Dependencies for everything injectable.** `Depends(get_db)`,
`Depends(current_user)`, `Depends(pagination)`. Dependencies are overridable in
tests, module-level globals are not.

---

## 2. Pydantic v2 validation

**Every request body and query set is a model.** No `dict`, no bare `Request`,
no manual `request.query_params.get()`.

**Always `extra="forbid"`.** Silently ignoring an unknown field means a client
typo (`presetSlugs` for `presetSlug`) becomes a mystery bug instead of a 422.

```python
class Base(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        alias_generator=to_camel,     # camelCase wire, snake_case Python
        populate_by_name=True,
        frozen=True,                  # request models are immutable
        protected_namespaces=(),      # we have many `model_id` fields; Pydantic
    )                                 #   reserves `model_` and would warn
```

**Constrain at the type, not in a validator.** A validator that re-checks length
is a rule that lives outside the schema and therefore outside the OpenAPI
document and the generated client.

```python
Prompt   = Annotated[str, StringConstraints(min_length=3, max_length=2000)]
Slug     = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{2,64}$")]
Handle   = Annotated[str, StringConstraints(pattern=r"^[a-z0-9._-]{3,32}$")]
Batch    = Annotated[int, Field(ge=1, le=4)]
Seed     = Annotated[int, Field(ge=0, le=9_999_999)]
PageSize = Annotated[int, Field(ge=1, le=60)]
```

**Where each kind of rule belongs.** Getting this wrong is the most common
FastAPI design mistake:

| Rule | Home | Why |
|---|---|---|
| Type, length, range, pattern, enum | Pydantic type | Static; appears in OpenAPI |
| Two fields must agree | `@model_validator(mode="after")` | Needs both fields, no I/O |
| Does this preset exist? | Service, via repository | Needs the database |
| Does this model allow `batch=4`? | Service | Needs a catalog read |
| Can this plan use motion? | Service | Needs the user's plan |
| Can this user afford it? | Service, inside the transaction | Must be atomic with the spend |

**A validator never does I/O.** No `await`, no database, no Redis. Validators run
during parsing, where a slow call blocks the request before you have even
rate-limited it, and where an exception surfaces as a confusing 422.

**Query parameters get models too**, via `Annotated[Query, Depends()]`:

```python
class WallQuery(Base):
    cursor: str | None = None
    limit:  PageSize = 24
    mode:   Mode | None = None
    preset: Slug | None = None
    q:      Annotated[str, StringConstraints(min_length=2, max_length=100)] | None = None

    @field_validator("q")
    @classmethod
    def normalise(cls, v: str | None) -> str | None:
        return sanitize_search(v) if v else None
```

**Response models are separate from DB models, always.** Returning a Prisma row
directly is how `storage_key`, `content_hash` and `deleted_at` leak into a public
API. Use `response_model=` and let FastAPI enforce it.

**Settings are a model.** `pydantic-settings`, validated at import, so a bad
environment is a boot failure and not a 3am 500:

```python
class Settings(BaseSettings):
    database_url: PostgresDsn
    direct_database_url: PostgresDsn
    redis_url: RedisDsn
    jwt_secret: Annotated[SecretStr, Field(min_length=32)]
    environment: Literal["dev", "test", "staging", "prod"] = "dev"
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")
```

---

## 3. Prisma schema and migrations

**The schema is the source of truth.** Never write DDL by hand except in the
cases below. Never edit a migration that has been applied anywhere but your
laptop.

```bash
npm run db:migrate -- --name add_asset_moderation_state   # dev: write + apply
npm run db:migrate:deploy                                 # CI/prod: apply only
npm run db:generate                                       # regenerate py client
npm run db:reset                                          # replay from zero
```

All of these wrap `python -m prisma`, never an npm `prisma` binary.
`prisma-client-py` vendors its own CLI and engines (5.17.0); running the npm CLI
against it is a version mismatch.

**Checklist for every new model:**

- [ ] `@@map("snake_case_plural")` — Postgres convention, not Prisma's default
- [ ] `id` is `uuid` for anything a client references; `autoincrement()` BigInt
      for append-only internals (ledger, audit) where ordering is useful
- [ ] `createdAt @default(now())` and `updatedAt @updatedAt`
- [ ] `deletedAt DateTime?` if the row is ever user-deletable
- [ ] Explicit `onDelete` on every relation — the default is not always right,
      and "what happens to their assets when a user is deleted" is a product
      question with a `Cascade` / `SetNull` / `Restrict` answer
- [ ] `@db.VarChar(n)` on every string. Unbounded `text` from a client is a
      denial-of-service vector
- [ ] Enum instead of `String` for any closed set
- [ ] Every index justified by a named query in the architecture's index map
- [ ] Money and credits are `Int`. Never `Float`

**Three things about hand-written migrations that cost real time here.** They
are not theoretical; each was found by running the migrations and looking at the
database afterwards.

1. **The runner stops after `CREATE EXTENSION`, silently.** Statements after it
   in the same file are skipped, no error is raised, and the migration is
   recorded as applied. The symptom is a missing index and a query that quietly
   degrades to a sequential scan. Extensions get a migration of their own.
2. **`migrate dev` generates `DROP INDEX` for any index Prisma cannot express.**
   The trigram GIN is drift from its point of view, so every `migrate dev` run
   proposes dropping it. Read the generated SQL and delete those lines.
3. **Always verify against the database, not the migration output.** `\d+ assets`
   or `pg_indexes`, after a `db:reset`. `tests/test_migrations.py` does this in
   CI, which is the only reason the first two are survivable.

**Write the migration by hand when Prisma cannot express it.** Four cases in this
project, all in `0002_constraints_and_indexes`:

```sql
-- CHECK constraints
ALTER TABLE users ADD CONSTRAINT users_credits_non_negative CHECK (credits >= 0);
-- partial indexes (much smaller, stay in cache)
CREATE INDEX assets_wall_feed_idx ON assets (published_at DESC, id DESC)
  WHERE published AND deleted_at IS NULL AND status = 'READY';
-- extensions and GIN
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX assets_prompt_trgm_idx ON assets USING gin (prompt gin_trgm_ops);
-- concurrent index creation on a live table
CREATE INDEX CONCURRENTLY ...;   -- must be its own migration, no transaction
```

**Columns are camelCase.** Tables are `@@map`-ed to `snake_case_plural`; columns
are not individually `@map`-ed. So every raw statement quotes its identifiers:
`"publishedAt"`, `"deletedAt"`, `"userId"`. Unquoted camelCase folds to
lowercase in Postgres and fails at runtime, not at review.

**Expand/contract, always.** Every migration must be safe against the *previous*
app version, because during a deploy both versions are serving.

To rename `foo` → `bar`: (1) add `bar`, (2) deploy code writing both and reading
`bar` with a `foo` fallback, (3) backfill, (4) deploy code using `bar` only,
(5) drop `foo`. Four deploys. The one-step rename is a guaranteed outage.

**Never** in a single migration: drop a column the running code still selects,
add a `NOT NULL` column without a default to a populated table, or change a
column's type in place.

**Seeds are idempotent.** `prisma/seed/` uses `upsert` keyed on the natural key,
so `db:seed` is safe to run repeatedly against a database with real data. The
seed also *validates* — a preset whose `template` lacks `{prompt}` fails the seed
loudly rather than shipping a preset that discards the user's input.

---

## 4. Query patterns

**Every query lives in a repository method.** One method, one query, one name
that says what it is for. This is what makes N+1 and missing indexes reviewable
in a diff.

```python
# api/app/repositories/assets.py
class AssetRepository:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def wall_page(self, *, cursor: Cursor | None, limit: int,
                        mode: Mode | None, preset: str | None,
                        q: str | None) -> list[Asset]:
        """One page of the public feed. Uses assets_wall_feed_idx."""
```

**`select` narrowly.** Ask for the columns the caller renders and no more. The
grid does not need `composedPrompt`; fetching it on 24 tiles is ~140 KB of
transfer for text nobody has hovered yet.

```python
await db.asset.find_many(
    where=...,
    # not include={"model": True} — authorHandle is denormalised for this reason
    order={"publishedAt": "desc"},
    take=limit + 1,
)
```

**Kill N+1 with `include`, or with denormalisation.** For the feed we chose
denormalisation (`authorHandle`, `likeCount`) because zero joins beats one join
at feed scale. Elsewhere, one `include` with a nested `select`. Never a loop with
an `await` inside it against the database.

```python
# WRONG — 24 round trips
for a in assets:
    a.model = await db.generationmodel.find_unique(where={"id": a.modelId})

# RIGHT — one round trip, or zero if the field is denormalised
assets = await db.asset.find_many(where=..., include={"model": {"select": {...}}})
```

**Raw SQL: positional parameters only.** Prisma has no string-building API to
misuse, so the only place injection can enter is `query_raw` / `execute_raw`.

```python
# RIGHT
await db.query_raw("SELECT id FROM assets WHERE prompt % $1 LIMIT $2", q, limit)

# WRONG — CI greps for exactly this and fails the build
await db.query_raw(f"SELECT id FROM assets WHERE prompt % '{q}'")
```

**Dynamic sort/filter through an allowlist dict.** An identifier can never be a
parameter, so it must never come from a user.

```python
SORTS = {"newest": "published_at DESC, id DESC",
         "popular": "like_count DESC, id DESC"}
clause = SORTS.get(query.sort)
if clause is None:
    raise BadRequest("sort", "Unknown sort.")   # 400, not a 500 or an injection
```

**Read the plan before you ship the query.** `EXPLAIN (ANALYZE, BUFFERS)` on
anything on a hot path. What we refuse to ship: a `Seq Scan` on `assets`, a
`Sort` node on the feed path, or a `Rows Removed by Filter` count much larger
than the rows returned.

---

## 5. Transactions and the money path

**Rules, in order of importance:**

1. **Enforce invariants in the database.** `CHECK (credits >= 0)`, unique
   constraints for idempotency. Application logic is the first line of defence;
   the schema is the last, and the last one is the one that holds under a race.
2. **No network I/O inside a transaction.** No upstream fetch, no Redis, no HTTP.
   A transaction held open across a network call holds a connection and a row
   lock for as long as someone else's server takes to answer.
3. **Enqueue after commit.** Inside, a rollback leaves a ghost task. After, a
   lost task is recovered by the `(status, queuedAt)` sweeper.
4. **Conditional `UPDATE` beats read-then-write.** Do the check in the `WHERE`.
5. **Ledger entries are append-only.** Never `UPDATE` a ledger row. A correction
   is a new compensating entry.
6. **Keep transactions short.** Every statement inside one is contention.

```python
async def submit(self, user: User, body: SubmitJobIn) -> Job:
    model, preset, ratio = await self._catalog.resolve(body)   # cached, outside
    self._assert_compatible(user, model, preset, body)         # pure, outside
    price = price_job(model, body.batch, preset)               # pure, outside

    async with self._db.tx() as tx:                            # short, only I/O
        job = await tx.job.create({...,  "creditsDebited": price.total})
        await tx.asset.create_many([...])                      # seeds resolved
        await debit_for_job(tx, user.id, price.total, job.id)   # atomic guard
    # committed
    await self._queue.enqueue("generate", job_id=job.id)       # after commit
    return job
```

**Test the race, not just the path.** The test that matters fires 50 concurrent
submits against a 40-credit balance and asserts that exactly the affordable
number succeeded, the balance is ≥ 0, and `SUM(ledger.delta) == users.credits`.
A money path without that test is untested.

---

## 6. Idempotency

Two layers, because each covers the other's failure.

- **Redis** (fast): `idem:{user_id}:{key}` → the serialised response, 24 h TTL.
  A retry inside the window replays the original response with
  `Idempotency-Replayed: true`. Set the key with `NX` *before* doing the work so
  two simultaneous retries cannot both proceed.
- **Postgres** (durable): `UNIQUE (userId, idempotencyKey)` on `jobs`. With Redis
  cold, the second insert raises a unique violation; catch it, load the existing
  job, return it. **This is the guarantee.** Redis is only the optimisation.

```python
async def submit_idempotent(self, user, key, body):
    if (cached := await self._redis.get(idem_key(user.id, key))) is not None:
        return replay(cached)
    if not await self._redis.set(lock_key(user.id, key), "1", nx=True, ex=60):
        raise Conflict("A request with this key is already in flight.")
    try:
        job = await self.submit(user, body)
    except UniqueViolationError:                       # the durable backstop
        job = await self._jobs.by_idempotency_key(user.id, key)
    await self._redis.set(idem_key(user.id, key), serialise(job), ex=86_400)
    return job
```

**Same key, different body → `422`.** Hash the body alongside the key; a client
reusing a key for a different request has a bug, and silently returning the old
response hides it.

---

## 7. Pagination

**Keyset, never offset.** `OFFSET n` scans and discards `n` rows, and on an
insert-heavy feed it duplicates and skips items across page boundaries.

**The sort key must be total.** `(publishedAt, id)` — never `publishedAt` alone.
Two assets published in the same millisecond with a non-total key means one of
them can be skipped or repeated at a page boundary.

**Recipe:**

```python
async def page(self, *, cursor, limit, **filters):
    where = build_where(filters)
    if cursor:
        ts, row_id = decode_cursor(cursor)
        where["OR"] = [                       # (ts, id) < (cursor_ts, cursor_id)
            {"publishedAt": {"lt": ts}},
            {"publishedAt": ts, "id": {"lt": row_id}},
        ]
    rows = await self._db.asset.find_many(
        where=where,
        order=[{"publishedAt": "desc"}, {"id": "desc"}],
        take=limit + 1,                       # +1 reveals hasMore, no COUNT
    )
    has_more, rows = len(rows) > limit, rows[:limit]
    return Page(
        data=rows,
        next_cursor=encode_cursor(rows[-1].publishedAt, rows[-1].id)
                    if has_more and rows else None,
        has_more=has_more,
    )
```

**Never `COUNT(*)` for `hasMore`.** Fetching `limit + 1` answers it for free; a
count is a second full scan of the filtered set.

**Cursors are opaque and HMAC-signed.** A client that can forge a cursor can hand
us a key that defeats the index. Signing makes a tampered cursor a `400`.

**No total count on the wall.** "1,482,903 frames" costs a full scan on every
page load. If the UI genuinely needs a number, it gets a cached approximation
from `pg_class.reltuples`.

---

## 8. Rate limiting and throttling

Three separate mechanisms. Know which one you need.

| Mechanism | Caps | Where | Denial |
|---|---|---|---|
| Rate limit | requests / window | Redis sliding window, middleware | `429` + `Retry-After` |
| Throttle | concurrent work | Redis semaphore, at submit | `429`, `reason: concurrency` |
| Backpressure | queue depth | checked before debit | `503` + `Retry-After` |

**Rate limiting rules:**

- State lives in **Redis, never in process memory.** A module-level counter (what
  the current frame proxy uses) resets on every cold start and is not shared
  between instances, so it does not limit anything.
- Check-and-increment must be **atomic** — one Lua script, not `GET` then `INCR`.
- Key on **user id when authenticated**, else a **salted hash** of
  `(ip, user-agent)`. Never a raw IP as a cache key; that is storing personal
  data for no reason.
- **Per-class limits**, not one global number (§10 of the architecture). `search`
  is a fifth of `read` because a trigram scan costs far more than a key lookup.
- Emit `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` on **every**
  response, so clients can self-regulate before being denied.
- **Fail open on Redis failure and alert** — except `generate`, which fails
  closed. Spending credits with a broken limiter is worse than not generating.

**Throttling rules:**

- Every permit acquisition has a **TTL longer than the job timeout**, so a
  crashed worker cannot leak a permit permanently.
- Release in a `finally:`. Always.
- The **global upstream token bucket** is what actually protects the third party.
  Per-user limits do not: a thousand users each within their limit still
  overwhelm one upstream.

**Circuit breaker** on the upstream: open after `k` consecutive failures, jobs
stay `QUEUED` rather than burning retries, half-open probe every 30 s. Nothing is
debited while open.

---

## 9. Sanitization and injection defence

**Trust boundary: everything from a client is hostile, including from our own
frontend.** Yup running in the browser is a UX feature. It is not a control.

**SQL injection**

- Parameterised queries only. `$1`, `$2`. No f-strings, no `%`, no `+`.
- CI greps `query_raw`/`execute_raw` for interpolation and fails the build.
- Identifiers (columns, tables, sort directions) come from an allowlist dict, never
  from user input.
- Ruff's `S` (bandit) rules run in CI.

**Text normalisation** — for every string that is stored, displayed to another
person, or used as a cache key:

1. NFKC normalise, so one glyph has one byte representation and caching works.
2. Strip zero-width characters and control characters. They are invisible in the
   UI and make two identical-looking prompts hash differently, which breaks
   dedupe and defeats any future content filter.
3. Collapse whitespace runs; trim.
4. Truncate to the column bound.
5. Reject if empty after all of the above.

**Handles** additionally: lowercase into `handleLower` for uniqueness, allowlist
`^[a-z0-9._-]{3,32}$`, and check a reserved-word list.

**XSS** — React escapes by default. Keep it that way: no
`dangerouslySetInnerHTML`, no user text in a `href`/`src`/`style`, strict CSP with
no `unsafe-inline`.

**SSRF** — the real risk in this codebase. `Asset.url` and `altUrl` are currently
client-side strings.

- **Never fetch a client-supplied URL.** Upstream URLs are constructed
  server-side from catalog rows plus validated parameters.
- Clients receive `/v1/frames/:assetId`, never an upstream or storage URL.
- Outbound hosts are allowlisted in config.

**File and byte handling** — before anything reaches storage: verify magic bytes,
decode the image header, cap dimensions and byte size, serve with
`X-Content-Type-Options: nosniff` and an explicit content type. Never trust a
declared content type.

**Secrets** — environment only, validated at boot, never logged. `SecretStr` so an
accidental `repr()` prints `**********`. Refresh tokens and session tokens are
stored as SHA-256 hashes: a database dump must not be a set of working
credentials.

---

## 10. Errors

**RFC 9457 `application/problem+json`, everywhere**, including validation
failures. One shape means one error handler in the client.

```json
{
  "type": "https://darkroom.dev/problems/insufficient-credits",
  "title": "Not enough credits",
  "status": 402,
  "detail": "That costs 18 credits and you have 12.",
  "instance": "/v1/jobs",
  "requestId": "01JD2K...",
  "required": 18,
  "available": 12
}
```

**Status codes we actually use:**

| Code | When | Not when |
|---|---|---|
| `400` | Malformed cursor, unknown sort key | A field failed validation (that is 422) |
| `401` | No or expired session | The user lacks permission (403) |
| `403` | Authenticated but not the owner | The resource does not exist (404) |
| `404` | Missing, **or** present but not the caller's | Never leak existence via 403 |
| `409` | Incompatible state: motion on a free plan | Insufficient credits (402) |
| `412` | `If-Match` failed on a publish | — |
| `422` | Pydantic validation failed | — |
| `429` | Rate limit or concurrency | Queue is full (503) |
| `502` | Upstream generator failed | Our bug (500) |
| `503` | Queue depth exceeded, breaker open | — |

`404` for another user's private asset, never `403`. A `403` confirms the id
exists, which is an enumeration oracle.

**Domain exceptions, not `HTTPException`, in services.** Services raise
`InsufficientCredits`, `PlanForbidsMotion`, `AssetNotFound`; a single exception
handler maps each to a problem document. That keeps services HTTP-free and
testable, and keeps status-code policy in one file.

**Never leak internals.** No stack traces, no SQL, no upstream response bodies in
a client-facing error. Log the detail with the `requestId`; return the id.

---

## 11. Background work

**ARQ over Redis.** Async-native, one dependency we already run.

**Every task is idempotent and re-entrant.** A task can be delivered twice and
can die halfway. Both must be safe. In practice: guard on current state rather
than assuming it (`if job.status != "QUEUED": return`), and rely on the
`UNIQUE (jobId, reason)` ledger constraint for refunds.

**Checklist for every task:**

- [ ] Idempotent — safe to run twice
- [ ] Bounded retries with exponential backoff **and full jitter** (without
      jitter, a thousand failed jobs retry in lockstep and reproduce the outage)
- [ ] An explicit timeout, shorter than the visibility timeout
- [ ] Terminal-state writes happen even on failure — a job must never be stuck in
      `RUNNING` forever
- [ ] Permits and locks released in `finally:`
- [ ] A sweeper covers lost messages: claim `QUEUED` older than *n* minutes,
      and fail `RUNNING` older than the timeout
- [ ] Structured logs carry `job_id` and `attempt`

**Claim rows with `FOR UPDATE SKIP LOCKED`** when a task polls for work, so two
workers never claim the same row and neither blocks on the other.

---

## 12. Frontend contract

**Yup mirrors Pydantic, field for field.** A schema-parity test asserts both agree
on bounds and enum sets; when one changes, CI fails until the other does.

**`useDebouncedValue(value, 300)` for search.** Plus: minimum 2 characters,
`AbortController` on every supersede, `useDeferredValue` on the rendered list.
The abort is not an optimisation — without it a slow response can land after a
newer one and repaint stale results.

**`useInfiniteCursor(endpoint, params)`** owns list state: appends pages on
`IntersectionObserver`, dedupes by id, resets when filters change. Never
reconstruct a cursor client-side; it is opaque and signed.

**Optimistic updates** on likes and publish only — cheap, reversible, and the
server is authoritative on conflict. **Never optimistic on credits.** The balance
comes from the server, because the whole point of the backend is that the client
does not get to decide what it has spent.

**`Idempotency-Key`** is a fresh UUID per *submission intent*, held across
retries of that submission. A new key per retry defeats the entire mechanism.

**One typed client** (`src/lib/api.ts`), generated from the OpenAPI schema. It
attaches the request id, parses problem+json into a typed error, and surfaces
`Retry-After` so a 429 renders a real countdown rather than a generic failure.

**SSE for the job tray**, with a 5 s polling fallback after two stream errors.
Mobile Safari and corporate proxies both drop long-lived connections.

---

## 13. Testing

**Real Postgres and real Redis** via `testcontainers`. Never SQLite, never a mock
database: half of this design is constraints, partial indexes and transaction
semantics, and a mock tests none of it.

**Function-scoped transaction rollback** for isolation — one container for the
session, each test in a transaction that rolls back. Fast and hermetic.

**The tests that carry the design:**

```python
async def test_concurrent_submits_cannot_overspend(db, user_with_40_credits):
    """The CHECK constraint and the conditional UPDATE, together."""
    results = await asyncio.gather(
        *[submit(user, batch_of_2_at_18_credits()) for _ in range(50)],
        return_exceptions=True,
    )
    ok = [r for r in results if not isinstance(r, Exception)]
    assert len(ok) == 1                          # 40 credits buys exactly one
    user = await db.user.find_unique(where={"id": user.id})
    assert user.credits >= 0
    assert user.credits == await ledger_sum(db, user.id)   # THE invariant

async def test_refund_is_idempotent(db, failed_job):
    first  = await refund_failed_outputs(db, failed_job)
    second = await refund_failed_outputs(db, failed_job)
    assert first > 0 and second == 0              # unique constraint held

async def test_partial_batch_refunds_only_the_failures(db, job_2_of_4_failed):
    ...

async def test_same_idempotency_key_charges_once(client, user):
    ...

async def test_wall_feed_uses_the_index(db, user):
    """Assert plans against volume, never against an empty table.

    The planner is right to scan four rows, so an EXPLAIN assertion on a fresh
    database tests table size rather than the index. Insert ~20k rows, ANALYZE,
    then assert -- and assert cost-independent properties where you can: whether
    the planner *prefers* an index shifts with statistics and bloat, which makes
    a flaky test out of something that is not a correctness property.
    """
    await seed_rows(db, user, 20_000)
    plan = await explain(db, wall_page_sql())
    assert "Seq Scan" not in plan and "Sort" not in plan
```

**Also required:** `schemathesis` fuzzing the OpenAPI schema (no `5xx`, no
unvalidated field), `k6` against a 100k-row seed for the §16 budget, and one
Playwright path that goes compose → job → library → publish → wall → remix
signed out, because that is the product.

---

## 14. Observability

**Structured logs only.** `structlog`, JSON, one line per request with
`request_id`, `user_id`, route, status, duration.

**Never log:** prompts at info level (user content), tokens, cookies, raw IPs,
full request bodies.

**`X-Request-Id`** from the BFF, through FastAPI, into worker tasks, returned in
every response and every problem document. One id links a browser error to a
worker log line.

**Metrics that mirror the product's promises**, not just the infrastructure's
health: `job_outcome_total` by status (refund rate is a product KPI),
`ledger_drift` (must be 0 — page on non-zero, it is money),
`ratelimit_denied_total` by class, `queue_depth`, `upstream_breaker_state`.

**Health endpoints are two, not one.** `/health` checks the process; `/health/ready`
checks Postgres and Redis. A load balancer that removes an instance because the
database is briefly slow makes an outage worse.

---

## 15. Lint, types, CI

`make check` is the gate, and it is the same command locally and in CI.

```make
check: lint typecheck test
lint:
	ruff check api/ --output-format=github
	ruff format --check api/
	npx eslint . --max-warnings 0
	npx tsc --noEmit
	lint-imports                       # routers -> services -> repositories
	./scripts/no-raw-sql-interp.sh     # bans f-strings in query_raw
typecheck:
	npx prisma validate
	mypy api/ --strict
test:
	pytest api/tests -q --cov=api/app --cov-fail-under=85
	npx vitest run
audit:
	pip-audit && npm audit --audit-level high
```

**Zero warnings.** `--max-warnings 0`, `mypy --strict`, no blanket `# type: ignore`
(a narrowed `# type: ignore[arg-type]` with a comment is acceptable), no
`eslint-disable` without a reason on the same line.

Before every commit: `make check` green, migration reviewed as SQL, new query has
an index and a plan, new endpoint has a Pydantic response model and a rate-limit
class.

---

## 16. Anti-patterns

Each of these is something that was either in the original client-side design or
is the default mistake in this stack.

| Anti-pattern | Why it is wrong | Instead |
|---|---|---|
| Credits in client state | The user owns the reducer; clear site data, spend forever | Server-side balance with a DB `CHECK` |
| Rate limiter in a module variable | Resets on cold start, not shared between instances | Redis + atomic Lua |
| `OFFSET` pagination | Scans and discards; duplicates rows under inserts | Keyset on a total sort key |
| `COUNT(*)` for `hasMore` | A second scan of the filtered set | Fetch `limit + 1` |
| Returning Prisma rows from a route | Leaks `storageKey`, `deletedAt`, internals | Explicit response model |
| `extra="ignore"` on requests | A client typo becomes a silent bug | `extra="forbid"` |
| Validation only in Yup | Trivially bypassed with `curl` | Pydantic is the contract |
| f-string SQL | Injection | `$1` positional parameters |
| Fetching a client-supplied URL | SSRF | Construct server-side from the catalog |
| Enqueue inside a transaction | Rollback leaves a ghost task | Enqueue after commit |
| Network I/O inside a transaction | Holds a connection and locks on someone else's latency | Do it before or after |
| Read-then-write on a balance | Two concurrent spends both pass the check | Conditional `UPDATE ... WHERE credits >= n` |
| `UPDATE` on a ledger row | Destroys the audit trail | Append a compensating entry |
| Retry without jitter | A thousand jobs retry in lockstep and reproduce the outage | Exponential backoff + full jitter |
| Polling a job tray per second | N requests/second per open tab | SSE, with polling as fallback |
| Unpooled Postgres from a serverless app | Connection exhaustion at trivial load | PgBouncer/Neon pooled endpoint |
| `403` for another user's resource | Confirms the id exists; enumeration oracle | `404` |
| Blocking call in `async def` | Stalls every concurrent request on the worker | `anyio.to_thread.run_sync` |
| `migrate deploy` on app boot | Two instances race; corrupted schema | A release step in CI |
| One-step column rename | Both app versions serve during a deploy | Expand/contract |
| Unbounded `text` from a client | Memory and storage DoS | `@db.VarChar(n)` |
| `Float` for credits | Rounding near money | `Int` |
| Compressing `text/event-stream` | gzip buffers; EventSource receives nothing and reports no error | `Content-Encoding: identity`, and no compression in the proxy |
| Testing SSE with `curl` alone | curl sends no `Accept-Encoding`, so it never reproduces the browser's buffering | Drive a real browser |
| Relative storage paths | Two processes with different working directories get different stores | Resolve against the repo root at boot |
| A config value with no implementation behind it | `STORAGE_BACKEND=s3` silently wrote to local disk | Validate at boot and fail loudly |
| Server rules stricter than the product's | A `preset.mode == model.mode` check made most of the wall un-remixable | Encode the rule the UI actually had |
