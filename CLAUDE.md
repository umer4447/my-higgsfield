@AGENTS.md

# Darkroom — working agreement

Darkroom is an AI image and motion generation app: a Next.js 16 frontend with an
own-design UI, and a **Python FastAPI backend** on Postgres with a real API, a
real credit ledger and a real job queue. There is no mock data and no hardcoded
response anywhere in the request path.

**Read before writing backend code:**

- [`architecture.md`](architecture.md) — the design and the reasons. Sections are
  numbered; cite them in PR descriptions.
- [`skills.md`](skills.md) — the playbooks. Copy-adaptable recipes for
  validation, queries, transactions, pagination, limits, errors, tests.

Those two are referenced rather than `@`-imported on purpose: together they are
~2,100 lines, and loading them into every session wastes the context that should
be spent on the task. Read the sections the task touches.

---

## The three product claims

These are not marketing lines; they are constraints on the code, and each has a
mechanism behind it. A change that weakens one is a change to the product.

1. **Every frame shows the prompt that made it, in full, with the template.**
   `Asset.prompt` and `Asset.composedPrompt` are denormalised onto the row so
   this is always true, even after a preset is edited.
2. **Cost is itemised before it is spent.** `POST /v1/jobs/quote` is
   authoritative and shares one pricing function with the debit. The button never
   shows a number the server did not compute.
3. **Signed out, the composer works.** An anonymous visitor gets a real `User`
   row and 40 credits. Claiming a handle upgrades that row and keeps the work.

And the fourth, which is why the ledger exists: **a failed generation is
refunded.** Nobody pays for a frame they did not get.

---

## Non-negotiables

Breaking one of these is a blocking review comment, not a nit.

**Money**
- `users.credits` is never written except alongside a `LedgerEntry` in the same
  transaction.
- Spend is a conditional `UPDATE ... WHERE credits >= $n`, never read-then-write.
- Ledger rows are append-only. A correction is a new compensating entry.
- `SUM(ledger.delta) == users.credits` for every user. A test asserts it; an
  alert pages on drift.
- Credits are `Int`. Never `Float`.

**Validation**
- Pydantic v2 is the contract. `extra="forbid"` on every request model.
- Yup mirrors it client-side for UX only. Never treat it as a control.
- A validator never does I/O. Rules needing a database read belong in a service.
- Response models are explicit. Never return a Prisma row from a route.

**Data access**
- Every query lives in a repository method. Routers never touch `prisma`.
- Raw SQL uses `$1` positional parameters. An f-string in `query_raw` fails CI.
- Dynamic sort/filter resolves through an allowlist dict. Never a user string in
  an identifier position.
- Every list endpoint is keyset-paginated with a total sort key. No `OFFSET`,
  no `COUNT(*)` for `hasMore`.
- Every new index is justified by a named query in architecture.md §5.

**Schema**
- `prisma/schema.prisma` is the source of truth. Never hand-write DDL except for
  CHECK constraints, partial indexes, extensions and `CONCURRENTLY` — those go in
  a reviewed migration.
- Expand/contract, always. Every migration is safe against the previous app
  version, because both serve during a deploy.
- `migrate deploy` runs as a CI release step, never on app boot.

**Limits**
- Rate-limit state lives in Redis, never in process memory.
- Every new endpoint declares a rate-limit class.
- Fail open on Redis failure and alert — except `generate`, which fails closed.

**Boundaries**
- No client-supplied URL is ever fetched. Upstream URLs are built server-side
  from catalog rows and validated parameters.
- Bytes are verified (magic bytes, header decode, size and dimension caps) before
  storage.
- Secrets in environment only, validated at boot, never logged. Session and
  refresh tokens stored hashed.
- `404`, not `403`, for another user's resource.

**Async**
- No blocking call in `async def`. CPU-bound work goes through
  `anyio.to_thread.run_sync`.
- No network I/O inside a transaction. Enqueue after commit.

**Streaming**
- Never compress `text/event-stream`. gzip buffers, and an `EventSource` behind
  it receives nothing while reporting no error at all.
- Verify streaming in a real browser. `curl` sends no `Accept-Encoding` by
  default and will not reproduce it.

**Quality**
- Zero lint warnings. `ruff`, `mypy --strict`, `eslint --max-warnings 0`,
  `tsc --noEmit`. No blanket `# type: ignore`, no unexplained `eslint-disable`.

---

## Commands

```bash
make install                # venv, deps, migrate, seed
docker compose up -d        # postgres:16.4 + redis:7.4

make dev                    # next                    :3000
make api                    # uvicorn --reload        :8000
make worker                 # generation worker

make db-migrate name=add_x  # create + apply a migration
make db-deploy              # CI / prod: apply only
make db-seed                # catalog + wall; idempotent, validates
make db-reset               # replay every migration from zero

make check                  # lint + typecheck + test — the CI gate
npm run e2e                 # browser end-to-end (stack must be running)
npm run e2e:headed          # ...and watch it happen
cd api && .venv/bin/python -m pytest tests/test_credits.py -q   # the money path
```

---

## Layering

```
routers/       HTTP only: parse, authorise, serialise, status codes
  ↓            may not import prisma or repositories
services/      business rules; the only layer with policy
  ↓            may not import fastapi
repositories/  every query; one method per query
  ↓
prisma/
core/          security, ratelimit, throttle, sanitize, pagination, errors
```

Enforced by `import-linter` in CI. A router that imports `prisma` fails the build.

---

## How to add an endpoint

1. Pydantic request and response models in `api/app/schemas/`, `extra="forbid"`,
   constraints on the types rather than in validators.
2. Repository method for each query. Check the plan with `EXPLAIN (ANALYZE,
   BUFFERS)`; add the index if it needs one, and record it in architecture.md §5.
3. Service function holding the rules. Domain exceptions, not `HTTPException`.
4. Router: thin. `response_model=`, a rate-limit class, ownership check.
5. If it is a list: keyset cursor via `core/pagination`, `limit` default 24 cap 60.
6. If it writes: accept `Idempotency-Key`; require it on anything that spends.
7. Tests: happy path, each validation boundary, ownership denial, and the race if
   money or uniqueness is involved.
8. Yup schema in `src/lib/schemas/` mirroring the Pydantic model; the parity test
   will fail until it matches.
9. Update the endpoint table in architecture.md §7.

## How to add a migration

1. Edit `prisma/schema.prisma`. Run `npm run db:migrate -- --name <what_it_does>`.
   These scripts wrap `python -m prisma`; never use an npm `prisma` binary, as
   `prisma-client-py` vendors its own CLI and engines.
2. **Read the generated SQL.** It is the part that runs against production data.
3. **Delete any `DROP INDEX` for a hand-written index.** Prisma manages indexes
   and treats the trigram GIN as drift, so it proposes dropping it on every
   `migrate dev`. This happens every time; it is not a one-off.
4. Backward-compatible with the previous app version, or split into expand and
   contract steps.
5. CHECK constraints, GIN indexes, extensions, `CONCURRENTLY`: hand-written,
   with a comment saying why Prisma cannot express it. **Extensions go in a
   migration of their own** — the runner silently stops executing a file after
   `CREATE EXTENSION` and still reports success.
6. `npm run db:reset`, then **verify against the database**, not the migration
   output. Add the object to `api/tests/test_migrations.py`.
7. Update the seed if the catalog changed. Run it twice to prove idempotency.

---

## Running the whole thing

```bash
make api      # :8000
make worker   # generation
npm run build && npm start   # :3000  — see the note below
npm run e2e
```

**The E2E runs against a production build, not `next dev`.** The dev server's
HMR websocket fails in headless Chromium here and client effects never run, so a
dev-server E2E reports an empty page and tells you nothing about your code.

## Definition of done

- [ ] `make check` green, zero warnings
- [ ] Real Postgres and Redis in tests; no mocked database
- [ ] Money paths have a concurrency test
- [ ] New queries have an index and a checked plan — asserted against
      volume, never against an empty table
- [ ] New endpoint has a response model, a rate-limit class, and an ownership check
- [ ] Migration reviewed as SQL and backward-compatible
- [ ] architecture.md updated if the contract, schema or index set changed
- [ ] `npm run e2e` green, with zero console errors
- [ ] No prompts, tokens, cookies or raw IPs in logs
- [ ] No new `Float`, no new `OFFSET`, no new f-string SQL

---

## Two things about this stack that are not what you expect

**Yup does not exist for Python.** The brief asked for both FastAPI and Yup. Yup
is JavaScript, so it runs in the browser for form UX; **Pydantic v2** is the
server-side authority. Do not go looking for a Python Yup, and do not let client
validation stand in for server validation. architecture.md §2.

**Prisma's supported client is Node, not Python.** The Prisma **schema** and
`prisma migrate` are the source of truth and own all DDL. Data access uses
`prisma-client-py` (community-maintained). If it blocks a query, drop to
`db.query_raw` with positional parameters; if it blocks us structurally, the data
layer moves to SQLAlchemy 2.0 against the same schema — which is exactly why
every query lives behind a repository. architecture.md §2.

**Motion is honest.** A real generated keyframe played under a browser-rendered
camera move, stated as such in the UI. `services/generation.py` is the single swap
point for a real video model; the job, ledger and storage model already
accommodate one. Do not write copy implying a frame-by-frame video model is wired
up.
