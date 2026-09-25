# Darkroom — Backend Architecture

Status: design, approved for build · Owner: platform · Last revised: 2026-09-25

---

## 1. Why this document exists

Darkroom today is a frontend with no server. Accounts, credits, the ledger, the
job engine and the library all live in `localStorage` (`src/lib/store.tsx`), and
generation is driven from the browser through a thin image proxy
(`src/app/api/frame/route.ts`). That was the right call for a deploy-anywhere
demo. It is the wrong call for a product, for three reasons that are not
cosmetic:

1. **Credits are not real.** The debit happens in a reducer the user owns. Clear
   site data and you have infinite credits. A currency enforced on the client is
   not a currency.
2. **Nothing is shared.** "The Wall" is seeded from a constant array. Publishing
   an asset publishes it to yourself. There is no feed, because there is no
   second person in the system.
3. **The generator is unprotected.** Prompt text, model choice and dimensions
   arrive from the client and are forwarded upstream. The pacing that keeps us
   inside the rate limit is a module-level variable in a serverless function,
   which resets on every cold start.

This document specifies the backend that fixes all three, and the API contract
the rebuilt frontend consumes. The product argument does not change: prompts
stay visible, cost stays itemised before you spend, and a stranger with no
account still gets a working composer. Those three claims are now enforced
server-side instead of asserted client-side.

---

## 2. Two deviations from the brief, stated up front

Both are named here so a reviewer does not have to discover them.

**Yup does not exist for Python.** Yup is a JavaScript schema library. The brief
asks for FastAPI *and* Yup, which cannot both describe the same validation pass.
The resolution is one schema per boundary:

| Boundary | Library | Job |
|---|---|---|
| Browser form → submit | **Yup** | Fail fast, inline, before a request is made |
| HTTP request → handler | **Pydantic v2** | The authority. Types, bounds, enums, coercion |
| Handler → database | Prisma types | Structural; enforced at compile and DB level |

Client validation is a courtesy. Server validation is the contract. The Yup
schemas in `src/lib/schemas/` are written to mirror the Pydantic models field for
field, and a contract test asserts they agree (§20).

**Prisma's supported client is Node, not Python.** `prisma-client-py` is
community-maintained and trails the Node client. Rather than abandon Prisma —
the schema language and `prisma migrate` are the genuinely valuable parts — we
split the roles:

- `prisma/schema.prisma` is the **single source of truth** for the schema.
- `prisma migrate` owns all DDL. Migrations are checked in, reviewed, applied
  in CI. **Run it as `python -m prisma`, never the npm `prisma` binary:**
  `prisma-client-py` vendors its own CLI and engines (5.17.0), and mixing the
  two gives an engine/CLI version mismatch. The `npm run db:*` scripts are thin
  wrappers around the Python CLI so there is one way to do it.
- `prisma-client-py` is the async data-access layer in FastAPI.
- **Escape hatch:** if the Python client blocks something (an unsupported
  aggregate, a CTE, a window function), that query drops to `db.query_raw()`
  with positional parameters. If it blocks us structurally, the data layer moves
  to SQLAlchemy 2.0 against the *same* Prisma-generated schema — a change to
  `api/app/db/` and nothing above it. Repository interfaces exist precisely to
  keep that swap cheap.

---

## 3. System topology

```
                          ┌──────────────────────────────┐
  browser ───────────────►│  Next.js 16 (Vercel)         │
   Yup · SSE · debounce   │  RSC + client components     │
                          │  /api/* → thin BFF proxy     │
                          └───────────┬──────────────────┘
                                      │ httpOnly cookie (JWT)
                                      ▼
                          ┌──────────────────────────────┐
                          │  FastAPI  (Python 3.12)      │
                          │  ─ Pydantic v2 validation    │
                          │  ─ auth · rate limit · CORS  │
                          │  ─ routers → services → repo │
                          └───┬───────────────┬──────────┘
                              │               │
                ┌─────────────▼──┐   ┌────────▼─────────┐
                │ Postgres 16    │   │ Redis            │
                │ (Neon, pooled) │   │ limits · buckets │
                │ Prisma schema  │   │ queue · cache    │
                └────────────────┘   └────────┬─────────┘
                                              │ ARQ
                                     ┌────────▼─────────┐
                                     │ Generation worker│
                                     │ token bucket     │
                                     │ retry · refund   │
                                     └────────┬─────────┘
                                              │
                              ┌───────────────▼───────────────┐
                              │ upstream diffusion endpoint   │
                              └───────────────┬───────────────┘
                                              ▼
                                     ┌──────────────────┐
                                     │ Object storage   │
                                     │ (Blob / S3)      │
                                     │ immutable frames │
                                     └──────────────────┘
```

**The single most important change:** generation moves behind the credit
transaction. Today the browser debits and then fetches. In this design the
client submits *parameters*, the server debits inside a transaction, enqueues,
and the worker generates. The client never learns the upstream URL and never
holds the authority to spend.

### Why a BFF proxy rather than browser → FastAPI direct

The Next `/api/*` routes stay, reduced to a pass-through. This buys three
things worth the extra hop: the auth cookie is same-origin (no third-party
cookie problem, no CORS preflight on every call), the FastAPI origin is not
publicly addressable and can sit behind a private network boundary, and Vercel's
WAF and BotID apply before a request costs us a Python worker. Latency cost is
~5–15ms same-region.

---

## 4. Repository layout

```
my-higgsfield/
├── src/                        # Next.js frontend (rebuilt UI, own design)
│   ├── app/
│   ├── components/
│   └── lib/
│       ├── api.ts              # typed fetch client, cursor helpers, SSE
│       ├── schemas/            # Yup schemas, mirroring Pydantic
│       └── hooks/              # useDebouncedValue, useInfiniteCursor, useJobStream
├── prisma/
│   ├── schema.prisma           # SOURCE OF TRUTH
│   ├── migrations/             # checked in, reviewed, CI-applied
│   └── seed/                   # catalog + wall seed, idempotent
├── api/                        # FastAPI service
│   ├── app/
│   │   ├── main.py             # app factory, lifespan, middleware order
│   │   ├── config.py           # pydantic-settings; fails fast on bad env
│   │   ├── deps.py             # DI: db, redis, current_user, pagination
│   │   ├── routers/            # health, auth, me, catalog, wall, assets,
│   │   │                       #   jobs, ledger, frames
│   │   ├── schemas/            # Pydantic request/response models
│   │   ├── services/           # business logic; the only layer with rules
│   │   │   ├── credits.py      # the money path
│   │   │   ├── jobs.py
│   │   │   ├── generation.py
│   │   │   └── feed.py
│   │   ├── repositories/       # every DB call lives here
│   │   ├── core/
│   │   │   ├── security.py     # JWT, cookies, hashing
│   │   │   ├── ratelimit.py    # sliding window + token bucket (Lua)
│   │   │   ├── throttle.py     # concurrency semaphores
│   │   │   ├── sanitize.py     # prompt/text normalisation
│   │   │   ├── pagination.py   # opaque signed cursors
│   │   │   ├── errors.py       # RFC 9457 problem+json
│   │   │   └── idempotency.py
│   │   └── workers/
│   │       ├── arq_worker.py
│   │       └── tasks.py
│   ├── tests/
│   ├── pyproject.toml          # ruff, mypy, pytest config
│   └── Dockerfile
├── architecture.md
├── skills.md
├── CLAUDE.md
└── AGENTS.md
```

Layering rule, enforced by an import-linter contract in CI:
`routers → services → repositories → prisma`. A router that touches `prisma`
directly fails the build. Services never import FastAPI.

---

## 5. Data model

`prisma/schema.prisma`. Decisions worth defending are annotated.

```prisma
generator client {
  provider             = "prisma-client-py"
  interface            = "asyncio"
  recursive_type_depth = 5
}

datasource db {
  provider  = "postgresql"
  url       = env("DATABASE_URL")        // pooled (PgBouncer/Neon) — runtime
  directUrl = env("DIRECT_DATABASE_URL") // unpooled — migrations only
}

// ── enums ───────────────────────────────────────────────────────────────
// Enums, not strings. The composer's options are a closed set; an invalid
// mode should be unrepresentable rather than validated for.

enum Mode          { IMAGE MOTION }
enum Engine        { FLUX TURBO KONTEXT }
enum PresetFamily  { CAMERA LIGHT STOCK WORLD }
enum Move          { PUSH PULL ORBIT WHIP CRANE FLOAT SHAKE DOLLY }

enum JobStatus {
  QUEUED
  RUNNING
  SUCCEEDED
  PARTIAL     // batch of 4, two frames landed — refund covers only the misses
  FAILED
  CANCELLED
}

enum AssetStatus  { PENDING RUNNING READY FAILED }

enum LedgerReason {
  SIGNUP_GRANT
  PLAN_GRANT
  MONTHLY_REFRESH
  JOB_DEBIT
  JOB_REFUND
  ADMIN_ADJUSTMENT
}

// ── identity ────────────────────────────────────────────────────────────

model User {
  id          String  @id @default(uuid()) @db.Uuid
  // A stranger gets a real row, not a null session. This is what keeps
  // "signed out still works" true without keeping it client-only.
  isAnonymous Boolean @default(true)
  handle      String? @db.VarChar(32)
  handleLower String? @unique @db.VarChar(32)   // case-insensitive uniqueness
  email       String? @unique @db.VarChar(320)
  emailVerifiedAt DateTime?

  // Materialised balance. The ledger is the truth; this column is the fast
  // read. A CHECK (credits >= 0) in migration 0002 makes overspend a
  // database error rather than a race we have to reason about.
  credits        Int      @default(40)
  planId         String
  creditsResetAt DateTime?

  createdAt  DateTime  @default(now())
  updatedAt  DateTime  @updatedAt
  lastSeenAt DateTime  @default(now())
  deletedAt  DateTime?

  plan     Plan          @relation(fields: [planId], references: [id])
  assets   Asset[]
  jobs     Job[]
  ledger   LedgerEntry[]
  likes    Like[]
  sessions Session[]

  @@index([planId])
  @@index([createdAt(sort: Desc)])
  @@index([lastSeenAt])                          // anonymous-user reaping
  @@map("users")
}

model Session {
  id        String    @id @default(uuid()) @db.Uuid
  userId    String    @db.Uuid
  // Refresh tokens are stored hashed. A database dump must not be a set of
  // working credentials.
  tokenHash String    @unique @db.Char(64)
  userAgent String?   @db.VarChar(400)
  ipHash    String?   @db.Char(64)               // hashed: we need rate-limit
  createdAt DateTime  @default(now())            //   identity, not an address
  expiresAt DateTime
  revokedAt DateTime?

  user User @relation(fields: [userId], references: [id], onDelete: Cascade)

  @@index([userId])
  @@index([expiresAt])
  @@map("sessions")
}

// ── catalog (was src/lib/catalog.ts) ────────────────────────────────────
// Moved into Postgres. Pricing and model availability must be changeable
// without a frontend deploy, and an asset must reference the model that
// actually produced it.

model Plan {
  id                String  @id @db.VarChar(64)   // "darkroom-studio"
  name              String  @db.VarChar(64)
  tagline           String  @db.VarChar(200)
  priceCents        Int
  monthlyCredits    Int
  maxBatch          Int     @default(4)
  maxConcurrentJobs Int     @default(1)           // feeds the throttle (§10)
  generatePerMinute Int     @default(6)           // feeds the rate limiter
  motionEnabled     Boolean @default(false)
  perks             String[]
  featured          Boolean @default(false)
  sortOrder         Int     @default(0)
  active            Boolean @default(true)

  users User[]
  @@map("plans")
}

model GenerationModel {
  id         String  @id @db.VarChar(64)          // "halide-2"
  name       String  @db.VarChar(64)
  vendor     String  @db.VarChar(64)
  mode       Mode
  engine     Engine
  creditCost Int                                  // credits per output
  maxBatch   Int     @default(4)
  blurb      String  @db.VarChar(300)
  badge      String? @db.VarChar(16)
  sortOrder  Int     @default(0)
  active     Boolean @default(true)

  assets Asset[]
  jobs   Job[]

  @@index([mode, active, sortOrder])
  @@map("generation_models")
}

model Preset {
  slug          String       @id @db.VarChar(64)
  name          String       @db.VarChar(64)
  family        PresetFamily
  mode          Mode
  description   String       @db.VarChar(400)
  // Must contain the literal {prompt}. Enforced by a CHECK in migration 0002
  // AND by the seed validator — a preset that drops the user's prompt is a
  // silent product bug, not a cosmetic one.
  template      String       @db.VarChar(2000)
  move          Move?
  previewPrompt String       @db.VarChar(400)
  previewSeed   Int
  sortOrder     Int          @default(0)
  active        Boolean      @default(true)

  assets Asset[]
  jobs   Job[]

  @@index([family, mode, active])
  @@map("presets")
}

model Ratio {
  id        String  @id @db.VarChar(16)           // "16:9"
  label     String  @db.VarChar(16)
  width     Int
  height    Int
  note      String  @db.VarChar(64)
  sortOrder Int     @default(0)
  active    Boolean @default(true)

  assets Asset[]
  jobs   Job[]
  @@map("ratios")
}

// ── work ────────────────────────────────────────────────────────────────

model Job {
  id     String @id @default(uuid()) @db.Uuid
  userId String @db.Uuid

  // Durable idempotency. The Redis replay cache (skills.md §6) makes a retry
  // fast; this unique
  // constraint makes a double-charge impossible even with Redis cold.
  idempotencyKey String @db.VarChar(128)

  status JobStatus @default(QUEUED)
  mode   Mode

  prompt         String  @db.VarChar(2000)       // what the user typed
  composedPrompt String  @db.VarChar(6000)       // after the preset template
  modelId        String  @db.VarChar(64)
  presetSlug     String? @db.VarChar(64)
  ratioId        String  @db.VarChar(16)
  batch          Int
  seed           Int?                             // null = server-chosen
  move           Move?

  // Priced once, at submit, from the catalog row as it was then. A later
  // price change must not retroactively alter what someone paid.
  creditsDebited  Int
  creditsRefunded Int @default(0)

  attempts   Int       @default(0)
  error      String?   @db.VarChar(500)
  queuedAt   DateTime  @default(now())
  startedAt  DateTime?
  finishedAt DateTime?
  createdAt  DateTime  @default(now())
  updatedAt  DateTime  @updatedAt

  user    User            @relation(fields: [userId], references: [id], onDelete: Cascade)
  model   GenerationModel @relation(fields: [modelId], references: [id])
  preset  Preset?         @relation(fields: [presetSlug], references: [slug])
  ratio   Ratio           @relation(fields: [ratioId], references: [id])
  outputs Asset[]
  ledger  LedgerEntry[]

  @@unique([userId, idempotencyKey])
  @@index([userId, createdAt(sort: Desc), id])    // job tray, keyset
  @@index([status, queuedAt])                     // worker sweep, stuck-job scan
  @@map("jobs")
}

model Asset {
  id     String  @id @default(uuid()) @db.Uuid
  userId String  @db.Uuid
  jobId  String? @db.Uuid                         // null for seeded wall items

  mode   Mode
  status AssetStatus @default(PENDING)

  // Denormalised from the job on purpose. The wall and the asset page must
  // render from one index scan without joining four catalog tables, and the
  // prompt shown must be the prompt used even if the preset later changes.
  prompt         String  @db.VarChar(2000)
  composedPrompt String  @db.VarChar(6000)
  modelId        String  @db.VarChar(64)
  presetSlug     String? @db.VarChar(64)
  ratioId        String  @db.VarChar(16)
  seed           Int
  move           Move?
  width          Int
  height         Int
  creditCost     Int
  authorHandle   String  @db.VarChar(32)          // avoids a join on the feed

  // Where the bytes are. Null until READY. The client is served a signed or
  // CDN URL derived from this — never a raw upstream URL.
  storageKey  String? @db.VarChar(400)
  contentHash String? @db.Char(64)                // sha256; dedupe + integrity
  bytes       Int?

  published   Boolean   @default(false)
  publishedAt DateTime?
  likeCount   Int       @default(0)               // counter, not COUNT(*)
  seeded      Boolean   @default(false)

  error     String?   @db.VarChar(500)
  createdAt DateTime  @default(now())
  updatedAt DateTime  @updatedAt
  deletedAt DateTime?                             // soft delete

  user   User            @relation(fields: [userId], references: [id], onDelete: Cascade)
  job    Job?            @relation(fields: [jobId], references: [id], onDelete: SetNull)
  model  GenerationModel @relation(fields: [modelId], references: [id])
  preset Preset?         @relation(fields: [presetSlug], references: [slug])
  ratio  Ratio           @relation(fields: [ratioId], references: [id])
  likes  Like[]

  @@index([userId, createdAt(sort: Desc), id])    // library, keyset
  @@index([publishedAt(sort: Desc), id])          // wall, keyset (see partial
  @@index([jobId])                                //   index in migration 0002)
  @@index([contentHash])
  @@index([presetSlug, publishedAt(sort: Desc)])  // "more in this preset"
  @@map("assets")
}

model Like {
  userId    String   @db.Uuid
  assetId   String   @db.Uuid
  createdAt DateTime @default(now())

  user  User  @relation(fields: [userId], references: [id], onDelete: Cascade)
  asset Asset @relation(fields: [assetId], references: [id], onDelete: Cascade)

  // Composite PK: one like per person per asset, enforced by the schema
  // rather than by a check-then-insert that races.
  @@id([userId, assetId])
  @@index([assetId])
  @@map("likes")
}

// ── money ───────────────────────────────────────────────────────────────

model LedgerEntry {
  id     BigInt  @id @default(autoincrement())
  userId String  @db.Uuid
  jobId  String? @db.Uuid

  reason       LedgerReason
  delta        Int                                // signed: -18, +18
  balanceAfter Int                                // audit; reconciles the
  note         String? @db.VarChar(200)           //   materialised column
  createdAt    DateTime @default(now())

  user User @relation(fields: [userId], references: [id], onDelete: Cascade)
  job  Job? @relation(fields: [jobId], references: [id], onDelete: SetNull)

  // The refund guard. One DEBIT and one REFUND per job, ever. Postgres treats
  // NULLs as distinct, so non-job entries (grants, refreshes) are unaffected.
  // A retried worker that tries to refund twice gets a constraint violation,
  // which is exactly the outcome we want.
  @@unique([jobId, reason])
  @@index([userId, createdAt(sort: Desc), id])     // ledger page, keyset
  @@map("ledger_entries")
}

// ── ops ─────────────────────────────────────────────────────────────────

model AuditLog {
  id        BigInt   @id @default(autoincrement())
  userId    String?  @db.Uuid
  action    String   @db.VarChar(64)
  subject   String?  @db.VarChar(128)
  metadata  Json?
  ipHash    String?  @db.Char(64)
  createdAt DateTime @default(now())

  @@index([userId, createdAt(sort: Desc)])
  @@index([action, createdAt(sort: Desc)])
  @@map("audit_logs")
}
```

### Column naming, and what it means for raw SQL

Tables are `@@map`-ed to `snake_case_plural`; **columns keep Prisma's camelCase**
and are not individually `@map`-ed. That is a deliberate trade: 150 `@map` lines
avoided, at the cost of quoting identifiers in the handful of raw queries. So
every raw statement in this codebase writes `"publishedAt"`, `"deletedAt"`,
`"userId"` with double quotes. Unquoted camelCase folds to lowercase in Postgres
and fails at runtime, not at review, so this is not optional.

### What Prisma cannot express, and where it lives instead

Four things this schema needs are outside Prisma's DSL. They go in a hand-written
migration, `prisma/migrations/0002_constraints_and_indexes/migration.sql`, which
is reviewed like any other code. Pretending Prisma covers these would be the
actual mistake.

```sql
-- 1. Credits can never go negative. The last line of defence on the money path.
ALTER TABLE users ADD CONSTRAINT users_credits_non_negative CHECK (credits >= 0);

-- 2. A preset that discards the user's prompt is a product bug. Ban it.
ALTER TABLE presets ADD CONSTRAINT presets_template_has_slot
  CHECK (template LIKE '%{prompt}%');

-- 3. A batch is bounded at the database, not only in Pydantic.
ALTER TABLE "jobs"
  ADD CONSTRAINT "jobs_batch_bounded" CHECK ("batch" >= 1 AND "batch" <= 8);

-- 4. Prompt search. Trigram beats a leading-wildcard LIKE and needs no
--    tsvector column: prompts are short, multilingual and not prose.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX "assets_prompt_trgm_idx"
  ON "assets" USING gin ("prompt" gin_trgm_ops);
```

**Three things this cost us, learned by running it rather than by reasoning:**

1. **A composite `(userId, prompt)` GIN needs the `btree_gin` extension** to get
   an operator class for `uuid`. Not worth a second extension: library search is
   already scoped to one user by the `(userId, createdAt, id)` btree, and one
   user holds hundreds of assets, not millions. Postgres BitmapAnds the two.
2. **The wall index is a plain composite, not a partial index.** A partial index
   would be smaller, but Prisma manages indexes and proposes dropping any it
   cannot express. Leading the composite on `published`
   (`@@index([published, publishedAt(sort: Desc), id(sort: Desc)])`) serves the
   same filtered query, stays Prisma-managed, and never drifts.
3. **`prisma migrate dev` generates `DROP INDEX` for the trigram index** on
   every run, because it is drift from Prisma's point of view. Read the
   generated SQL and delete those lines. This is a documented workflow step, not
   a one-off; see CLAUDE.md, "How to add a migration".

**A silent failure mode worth knowing about.** The Prisma migration runner stops
executing a migration file after `CREATE EXTENSION`: the later statements are
skipped, no error is raised, and the migration is recorded as applied. The
symptom is an index that is simply absent. Extensions therefore get a migration
of their own, and `tests/test_migrations.py` asserts that every constraint and
index actually exists after a clean replay.

### Index-to-query map

Every index above exists for a named query. An index without one gets deleted.

| Query | Index | Plan |
|---|---|---|
| Wall feed, page N | `assets_wall_feed_idx` | Index-only scan, no sort |
| Library, filtered + paged | `assets(userId, createdAt desc, id)` | Index scan |
| Prompt search | `assets_prompt_trgm_idx` | Bitmap index scan |
| Job tray | `jobs(userId, createdAt desc, id)` | Index scan |
| Worker claim | `jobs(status, queuedAt)` | Index scan, `SKIP LOCKED` |
| Ledger page | `ledger_entries(userId, createdAt desc, id)` | Index scan |
| Liked-by-me hydration | `likes` PK `(userId, assetId)` | Index-only scan |
| Anonymous reaping | `users(lastSeenAt)` | Range scan |

---

## 6. The money path

This is the part that has to be right. Everything else is a feed.

**Invariants.** All four are enforced by the database, not by application care:

1. A user's balance is never negative. → `CHECK (credits >= 0)`
2. A job is debited exactly once. → `UNIQUE (userId, idempotencyKey)` on `jobs`
3. A job is refunded at most once. → `UNIQUE (jobId, reason)` on `ledger_entries`
4. `users.credits` always equals the sum of that user's `ledger.delta`. →
   asserted by a nightly reconciliation job that alerts on drift

**Debit, in one transaction.** The conditional `UPDATE` is the whole trick: it
does the balance check and the decrement in a single atomic statement, so there
is no read-then-write window for two concurrent submits to race through. No
`SELECT ... FOR UPDATE`, no advisory lock, no retry loop.

```python
# api/app/services/credits.py
async def debit_for_job(db: Prisma, user_id: str, amount: int,
                        job_id: str) -> int:
    """Atomically spend `amount`. Returns the new balance.

    Raises InsufficientCredits if the balance would go negative. The WHERE
    clause is the guard: zero rows updated means the user could not afford it,
    and no state changed. Parameterised positionally — never interpolated.
    """
    rows = await db.query_raw(
        """
        UPDATE users
           SET credits = credits - $2, updated_at = now()
         WHERE id = $1 AND credits >= $2 AND deleted_at IS NULL
        RETURNING credits
        """,
        user_id, amount,
    )
    if not rows:
        raise InsufficientCredits(required=amount)

    balance = rows[0]["credits"]
    await db.ledgerentry.create({
        "userId": user_id, "jobId": job_id,
        "reason": "JOB_DEBIT", "delta": -amount, "balanceAfter": balance,
    })
    return balance
```

Called inside `async with db.tx() as tx:` alongside the `Job` and `Asset` row
creation, so a submission is all-or-nothing: no orphaned job with no debit, no
debit with no job.

**Refund.** The worker refunds only the outputs that actually failed — a batch of
four where two frames landed refunds two credits, and the job lands in `PARTIAL`.
The refund is idempotent by constraint, so a worker that crashes after refunding
but before marking the job done can safely re-run: the second attempt hits
`UNIQUE (jobId, reason)`, we catch it, and we treat it as already done.

```python
async def refund_failed_outputs(db, job) -> int:
    failed = sum(1 for o in job.outputs if o.status == "FAILED")
    if failed == 0:
        return 0
    per_output = job.model.creditCost + (1 if job.preset and job.preset.move else 0)
    amount = failed * per_output
    try:
        async with db.tx() as tx:
            rows = await tx.query_raw(
                "UPDATE users SET credits = credits + $2 WHERE id = $1 "
                "RETURNING credits",
                job.userId, amount,
            )
            await tx.ledgerentry.create({
                "userId": job.userId, "jobId": job.id,
                "reason": "JOB_REFUND", "delta": amount,
                "balanceAfter": rows[0]["credits"],
                "note": f"{failed} of {job.batch} outputs failed",
            })
            await tx.job.update(
                where={"id": job.id},
                data={"creditsRefunded": amount},
            )
    except UniqueViolationError:
        log.info("refund already applied", job_id=job.id)  # idempotent
        return 0
    return amount
```

**Pricing is a real endpoint, not a client formula.** "Cost before you spend" is
one of the three product claims, so the number on the button comes from the
server that will charge it. `POST /v1/jobs/quote` returns the same itemisation
the debit will use, computed by the same function. The client may render it
optimistically, but the quote endpoint is authoritative and the submit response
echoes the charge.

---

## 7. API surface

`/v1` prefix. JSON only. Cookie auth. Every list endpoint is cursor-paginated.

### Conventions

- **Envelope on collections:** `{ "data": [...], "meta": { "nextCursor", "hasMore", "limit" } }`.
  Single resources are returned bare. Collections need pagination metadata
  somewhere, and a sibling key beats a header the fetch client has to unpack.
- **Errors:** RFC 9457 `application/problem+json` — `type`, `title`, `status`,
  `detail`, `instance`, plus `errors[]` for field-level validation failures.
- **camelCase on the wire.** Python stays `snake_case` internally; Pydantic
  models set `alias_generator=to_camel` with `populate_by_name=True`, so the
  service speaks PEP 8 and the API speaks the frontend's language. The
  alternative — `snake_case` JSON — buys nothing and costs a mapping layer in
  every client call. One convention, chosen once, applied everywhere.
- **Idempotency:** `Idempotency-Key` header required on `POST /v1/jobs`,
  accepted on all other writes.
- **Concurrency control:** `ETag` on catalog and asset reads; `If-Match`
  required on `PATCH /v1/assets/:id` to prevent lost updates.

| Method | Path | Purpose | Auth | Limit class |
|---|---|---|---|---|
| `GET` | `/v1/health` | Liveness: process only | — | exempt |
| `GET` | `/v1/health/ready` | Readiness: DB + Redis ping | — | exempt |
| `POST` | `/v1/auth/anonymous` | Create anon user, grant 40 credits, set cookies | — | `auth` |
| `POST` | `/v1/auth/claim` | Attach a handle to the current anon user | session | `auth` |
| `POST` | `/v1/auth/refresh` | Rotate access token from refresh cookie | refresh | `auth` |
| `POST` | `/v1/auth/logout` | Revoke session | session | `auth` |
| `GET` | `/v1/me` | Account, plan, credits, concurrency headroom | session | `read` |
| `PATCH` | `/v1/me/plan` | Switch plan (demo billing; audited) | session | `write` |
| `GET` | `/v1/catalog` | Models, presets, ratios, plans in one payload | — | `read` |
| `GET` | `/v1/wall` | Public feed. Keyset paged, filterable, searchable | optional | `read` |
| `GET` | `/v1/library` | Caller's own assets. Paged, filtered, searchable | session | `read` |
| `GET` | `/v1/assets/:id` | One asset with full prompt + remix parameters | optional | `read` |
| `PATCH` | `/v1/assets/:id` | Publish / unpublish. `If-Match` required | owner | `write` |
| `DELETE` | `/v1/assets/:id` | Soft delete | owner | `write` |
| `PUT` | `/v1/assets/:id/like` | Like (idempotent by composite PK) | session | `write` |
| `DELETE` | `/v1/assets/:id/like` | Unlike | session | `write` |
| `POST` | `/v1/jobs/quote` | Itemised cost, authoritative | session | `read` |
| `POST` | `/v1/jobs` | Submit. Validates → prices → debits → enqueues | session | `generate` |
| `GET` | `/v1/jobs` | Job tray. Paged, filter by status | session | `read` |
| `GET` | `/v1/jobs/:id` | One job with output states | owner | `read` |
| `POST` | `/v1/jobs/:id/cancel` | Cancel if still `QUEUED`; refunds in full | owner | `write` |
| `GET` | `/v1/jobs/stream` | **SSE** — live job + output transitions | session | `stream` |
| `GET` | `/v1/ledger` | Every debit and refund, itemised, paged | session | `read` |
| `GET` | `/v1/frames/:assetId` | 302 → CDN/signed storage URL. Long cache | optional | `read` |

### One thing about SSE behind a proxy

`text/event-stream` and response compression do not mix. Next's rewrite proxy
gzips proxied responses, and gzip buffers: the browser's `EventSource` then
receives **nothing at all** until the buffer flushes, which on an idle job stream
is never. The stream connects, reports 200, and delivers silence, so the client
never even sees an error to fall back from.

`curl` hides this completely, because it sends no `Accept-Encoding` by default.
Only a real browser shows it. The fixes, both applied: the SSE response declares
`Content-Encoding: identity`, and `compress: false` in `next.config.ts` (the
platform or CDN compresses at the edge, which is where it belongs).

### Why SSE rather than polling

The job tray is the one surface that needs push. Today it polls its own reducer;
against a server, polling a tray with four in-flight jobs at 1s costs four
requests a second per open tab. One SSE connection per tab, multiplexed over
Redis pub/sub, replaces all of it. Events are `job.updated`, `output.ready`,
`output.failed`, `credits.changed`. Client falls back to 5s polling of
`GET /v1/jobs?status=active` if the stream errors twice — mobile Safari and
corporate proxies both drop long-lived connections.

### Scalability notes on the contract

- **No endpoint returns an unbounded list.** `limit` defaults to 24, caps at 60.
- **Every list is keyset-paged**, so page 400 costs what page 1 costs.
- **Sparse fieldsets** via `?fields=` on the wall, so the grid can fetch tiles
  without the 6 KB composed prompt it does not render until hover.
- **The catalog is one request, cached hard.** It changes on deploy, not per
  user. `Cache-Control: public, max-age=300, stale-while-revalidate=3600` plus
  an ETag; the client keeps it in a module-level cache.
- **Bulk read for remix.** `GET /v1/assets?ids=a,b,c` (max 50) so opening a
  library page does not fire 24 requests.

---

## 8. Pagination

Offset pagination is wrong here and the reason is mechanical: `OFFSET 10000`
makes Postgres walk and discard ten thousand rows, and on a feed where new rows
land at the top, page 2 silently re-shows items from page 1. Both problems get
worse exactly as the product succeeds.

**Keyset (cursor) pagination everywhere.** The cursor is the last row's sort key.
For the wall that is `(publishedAt, id)` — `id` breaks ties so the ordering is
total and the page boundary is unambiguous.

```sql
SELECT ... FROM assets
 WHERE published AND deleted_at IS NULL AND status = 'READY'
   AND (published_at, id) < ($1, $2)      -- the cursor
 ORDER BY published_at DESC, id DESC
 LIMIT $3 + 1;                            -- +1 to detect hasMore, no COUNT
```

That row-comparison predicate matches `assets_wall_feed_idx` exactly, so the plan
is an index scan that stops after `limit + 1` rows regardless of table size. And
we never run `COUNT(*)` to compute `hasMore` — fetching one extra row answers it
for free.

**Cursors are opaque and signed.** A client that can hand-craft a cursor can hand
us a key that defeats the index or leaks ordering internals. So we base64url a
small payload and HMAC it with the app secret:

```python
# api/app/core/pagination.py
def encode_cursor(ts: datetime, row_id: str) -> str:
    body = b64url(json.dumps({"v": 1, "t": ts.isoformat(), "i": row_id}))
    sig  = b64url(hmac.new(SECRET, body.encode(), "sha256").digest()[:16])
    return f"{body}.{sig}"

def decode_cursor(cursor: str) -> tuple[datetime, str]:
    body, _, sig = cursor.partition(".")
    if not hmac.compare_digest(sig, expected_sig(body)):
        raise InvalidCursor()                 # 400, not 500
    ...
```

A tampered cursor is a `400`, not a stack trace. Versioning the payload (`v: 1`)
means we can change the sort key later without breaking in-flight clients.

**Client side.** `useInfiniteCursor(endpoint, params)` holds
`{ pages, nextCursor, isLoading }`, appends on `IntersectionObserver`, dedupes by
id on append (belt and braces), and resets when filters change.

---

## 9. Validation, sanitization, injection

Four layers, each assuming the one before it was bypassed.

### Layer 1 — Yup, in the browser

Real validation with a real job: no wasted round trip, and errors appear next to
the field. Never trusted.

```ts
// src/lib/schemas/job.ts
export const submitSchema = object({
  prompt: string().trim()
    .min(3, "A few more words.")
    .max(2000, "That is longer than any model will read.")
    .required("Write a prompt first."),
  modelId: string().oneOf(catalogModelIds).required(),
  ratioId: string().oneOf(catalogRatioIds).required(),
  presetSlug: string().oneOf([...catalogPresetSlugs, null]).nullable(),
  batch: number().integer().min(1).max(4).required(),
  seed: number().integer().min(0).max(9_999_999).nullable(),
}).noUnknown();
```

### Layer 2 — Pydantic v2, the contract

This is the authority. Bounds, enums, and `extra="forbid"` so an unexpected field
is a `422` rather than something we silently ignore. Cross-field rules that need
the catalog (does this model support motion? is `batch` within this model's
`maxBatch`? is this preset's mode compatible?) run in the service, because they
need a database read and a validator should not.

```python
# api/app/schemas/job.py
class SubmitJobIn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        # Pydantic v2 reserves the `model_` prefix. Without this, every
        # `model_id` field in this codebase emits a protected-namespace warning
        # at import. We have a lot of them — Darkroom's domain noun for a
        # generator is "model" — so the namespace is released once, in the base.
        protected_namespaces=(),
    )

    prompt:      Annotated[str, StringConstraints(min_length=3, max_length=2000)]
    model_id:    Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{2,64}$")]
    ratio_id:    Annotated[str, StringConstraints(pattern=r"^\d{1,2}:\d{1,2}$")]
    preset_slug: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{2,64}$")] | None = None
    batch:       Annotated[int, Field(ge=1, le=8)]  # global ceiling only
    seed:        Annotated[int, Field(ge=0, le=9_999_999)] | None = None

    # `batch` carries only the global ceiling, matching the database CHECK. The
    # real caps are per-model (GenerationModel.maxBatch) and per-plan
    # (Plan.maxBatch) and are enforced in the service, because they are data. A
    # plan cap hardcoded here makes a paid plan unable to use a batch size it is
    # advertised as having -- which it did, until a test caught it.

    @field_validator("prompt")
    @classmethod
    def clean(cls, v: str) -> str:
        return sanitize_prompt(v)   # see layer 3
```

Note the patterns on the id fields. They are not the real check — the real check
is the foreign key — but they mean a malformed id is rejected before it costs a
query, which is what makes an id-stuffing flood cheap to absorb.

### Layer 3 — Normalisation

Prompts are freeform text that gets stored, displayed to other people, shipped to
a third party, and used as a cache key. Each of those wants it normalised.

```python
# api/app/core/sanitize.py
ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))

def sanitize_prompt(raw: str) -> str:
    s = unicodedata.normalize("NFKC", raw)          # one byte form per glyph,
    s = s.translate(ZERO_WIDTH)                     #   so caching works
    s = "".join(c for c in s if c == "\n" or unicodedata.category(c)[0] != "C")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if not s:
        raise ValueError("Prompt is empty after normalisation.")
    return s[:2000]
```

Control characters and zero-width joiners are stripped because they are invisible
in the UI and let two visually identical prompts hash differently — which breaks
dedupe and is a cheap way to bypass any content filter we add later. **Handles**
get their own pass: NFKC, lowercase for the uniqueness column, a
`^[a-z0-9._-]{3,32}$` allowlist, and a reserved-word list (`admin`, `api`,
`darkroom`, …).

**Output encoding.** React escapes by default, so prompts render safely, but the
one place that is not true is anywhere we would use `dangerouslySetInnerHTML`
(we do not) or a `style`/`href` built from user text (we do not). A strict CSP
backs it up: `default-src 'self'; img-src 'self' <cdn>; script-src 'self'`, no
`unsafe-inline`.

### Layer 4 — SQL and SSRF

- **Every query is parameterised.** Prisma does this structurally; there is no
  string-building API to misuse. Raw queries use `query_raw` with `$1, $2`
  positional parameters only.
- **CI bans the alternative.** A ruff rule plus a grep gate fails any build
  containing an f-string or `%`/`+` concatenation inside a `query_raw` or
  `execute_raw` call. The discipline is enforced, not remembered.
- **Identifiers are never dynamic.** Sort and filter parameters map through an
  explicit dict (`{"newest": "created_at DESC"}`); a value not in the dict is a
  `400`. No user string ever reaches a column or table position.
- **No client-supplied URL is ever fetched.** This is a real regression risk
  here, because `Asset.url` and `altUrl` are currently client-side strings. In
  this design the upstream URL is *constructed server-side* from catalog rows and
  validated parameters, and the client only ever receives
  `/v1/frames/:assetId`. That closes the SSRF door the current model leaves open.
- **Bytes are verified before storage.** The worker checks magic bytes and
  decodes the image header, capping dimensions and file size, before anything is
  written to object storage or served with an image content type.

---

## 10. Rate limiting and throttling

These are three different mechanisms solving three different problems. Conflating
them is why services fall over.

### (a) Rate limiting — requests per unit time

Redis sliding-window counter, executed as a Lua script so check-and-increment is
atomic across every FastAPI instance. The current `MIN_GAP_MS` in the frame proxy
is a module-level variable that resets on cold start — it does not survive the
platform it runs on. This does.

```lua
-- api/app/core/ratelimit.lua  — atomic sliding window
local key, now, window, limit = KEYS[1], tonumber(ARGV[1]),
                                tonumber(ARGV[2]), tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local used = redis.call('ZCARD', key)
if used >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, limit - used, oldest[2] + window - now}   -- denied, retry-after
end
redis.call('ZADD', key, now, now .. ':' .. ARGV[4])
redis.call('PEXPIRE', key, window)
return {1, limit - used - 1, window}
```

**Identity:** authenticated user id when present, else a salted hash of
`(ip, user-agent)`. Never the raw IP as a key — it is personal data sitting in a
cache with a long TTL. The salted hash gives us the same partitioning without
storing an address.

**Classes**, because one global number is either too strict for reads or too
loose for generation:

| Class | Free | Studio | Plate | Window |
|---|---|---|---|---|
| `read` | 120 | 300 | 600 | 60s |
| `search` | 20 | 60 | 120 | 60s |
| `write` | 30 | 90 | 180 | 60s |
| `auth` | 10 | 10 | 10 | 60s |
| `generate` | 6 | 30 | 90 | 60s |
| `stream` | 3 concurrent | 6 | 12 | — |

`search` is deliberately tighter than `read`: a trigram scan costs far more than
an index lookup, and search is the endpoint a debounce bug will hammer.

**Response on denial:** `429` + problem+json, with `RateLimit-Limit`,
`RateLimit-Remaining`, `RateLimit-Reset` and `Retry-After`. Successful responses
carry the same headers so a well-behaved client can back off before being told
to. The frontend reads `Retry-After` and shows a real countdown instead of a
generic failure.

**Fail-open, loudly.** If Redis is unreachable, requests are allowed and an alert
fires. A cache outage should degrade our protection, not take down the product.
The one exception is `generate`, which fails *closed* — spending money without a
working limiter is worse than a brief inability to generate.

### (b) Throttling — concurrent work in flight

Rate limiting caps arrival. Throttling caps simultaneity, which is what actually
protects the upstream generator and our own worker pool.

- **Per-user job concurrency** from `Plan.maxConcurrentJobs`. A Redis semaphore
  keyed `throttle:jobs:{userId}`, acquired at submit and released on terminal
  state, with a TTL well past the job timeout so a crashed worker cannot leak a
  permit forever. Over the cap gets a `429` with `reason: "concurrency"` — a
  different message from a rate-limit denial, because it means "wait for your
  own jobs", not "slow down".
- **Global upstream token bucket** in the worker: `N` tokens refilling at the
  rate the upstream tolerates. This is the server-side replacement for
  `loader.ts`'s `MAX_IN_FLIGHT = 4` and the proxy's `MIN_GAP_MS` — same idea,
  now shared across instances and durable across restarts.
- **Queue-depth backpressure.** Past a configured depth, `POST /v1/jobs` returns
  `503` with `Retry-After` *before* debiting. Never take the money and then
  admit we cannot do the work.

### (c) Retries and circuit breaking

Worker retries with exponential backoff and full jitter (3 attempts), which is
what the current proxy does correctly and should keep doing. Added: a circuit
breaker per upstream — after `k` consecutive failures the breaker opens, jobs
stay `QUEUED` rather than burning attempts, and a half-open probe every 30s
tests recovery. Nothing is debited while the breaker is open.

---

## 11. The generation pipeline

```
POST /v1/jobs
  │
  ├─ rate limit        (generate class, plan-derived)          → 429
  ├─ throttle          (per-user concurrency semaphore)        → 429
  ├─ idempotency       (Redis replay; DB unique as backstop)   → 200 cached
  ├─ Pydantic          (shape, bounds, enums)                  → 422
  ├─ catalog load      (model/preset/ratio, one cached read)   → 404
  ├─ compatibility     (mode match, batch ≤ model.maxBatch,
  │                     motion requires plan.motionEnabled)    → 409
  ├─ price             (same function the debit uses)
  ├─ queue depth check                                         → 503
  │
  └─ TRANSACTION ──────────────────────────────────────────────────────┐
       create Job (QUEUED)                                            │
       create N Assets (PENDING) with resolved seeds                   │
       debit credits (conditional UPDATE)                              │
       append LedgerEntry (JOB_DEBIT)                                  │
     COMMIT ────────────────────────────────────────────────────────────┘
       │
       └─ enqueue ARQ task, keyed by job id  ← after commit, never inside
            │
            ▼
       worker: claim → RUNNING → per output:
            acquire upstream token
            build upstream URL server-side from catalog + params
            fetch with timeout
            verify magic bytes, decode header, cap dimensions
            sha256 → contentHash → dedupe check
            put to object storage (immutable key)
            Asset → READY, storageKey set
            publish SSE event
            │
            ├─ all ready      → Job SUCCEEDED
            ├─ some failed    → refund failed count → Job PARTIAL
            └─ all failed     → refund in full      → Job FAILED
            │
            └─ release concurrency permit (finally:)
```

Three details that matter more than they look:

**Enqueue after commit, never inside the transaction.** A task enqueued inside a
transaction that then rolls back leaves a worker looking for a job that does not
exist. A task enqueued after commit can at worst be lost, which the
`(status, queuedAt)` sweeper picks up within a minute. Losing work is recoverable;
inventing work is not.

**Seeds are resolved at submit, not at generation.** `Job.seed` may be null
(meaning "surprise me"), but each `Asset` gets a concrete seed written before the
transaction commits. That is what makes Remix exact — the promise the product is
built on — and it makes generation deterministic and therefore cacheable and
retryable without drift.

**`contentHash` enables real dedupe.** Identical parameters produce identical
bytes. If the hash already exists in storage, the worker links to the existing
object instead of writing a second copy. The current design gets this
accidentally via URL-keyed CDN caching; here it is explicit and survives a CDN
purge.

**The storage root is absolute.** `STORAGE_LOCAL_DIR` is resolved against the
repository root at boot, not against the process working directory. The API runs
from `api/` and the seed from the root; with a relative path the two write to
different stores, and the symptom is every frame 404ing while the files plainly
exist on disk.

**Object storage keys** are content-addressed:
`frames/{contentHash[:2]}/{contentHash}.{ext}`. Immutable, so
`Cache-Control: public, max-age=31536000, immutable` is honest. The two-character
prefix keeps directory listings sane at volume.

---

## 12. Search, and debouncing

Prompt search is the library's main affordance and the wall's discovery path. It
is also the easiest endpoint to accidentally DDoS from your own frontend.

### Client

```ts
// src/lib/hooks/useDebouncedValue.ts
export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(t);          // the cleanup IS the debounce
  }, [value, delay]);
  return settled;
}
```

Used with three more guards, because a debounce alone is not enough:

1. **300 ms** — long enough to skip intra-word keystrokes, short enough to feel
   live. Below ~200 ms you are firing per keystroke with extra steps.
2. **Minimum 2 characters.** A one-character trigram query matches most of the
   table and is pure load for no useful result.
3. **`AbortController` on every supersede.** Without it, a fast typist's fourth
   response can arrive after the fifth and repaint stale results — a correctness
   bug, not a performance one. The in-flight request is cancelled on the next
   keystroke.
4. **`useDeferredValue`** on the grid so the input never janks while React
   reconciles a 24-tile repaint.

The input stays fully controlled and instant; only the *fetch* is debounced.

### Server

The client debounce is an optimisation the server does not rely on:

- `q` is capped at 100 characters, minimum 2, normalised through
  `sanitize_prompt` so the cache key is stable.
- `search` is its own rate-limit class at a fifth of `read` (§10).
- Trigram GIN index does the work; `similarity()` orders results and a
  `% ` threshold cuts the long tail.
- Hot queries cache in Redis for 30 s keyed on
  `(scope, normalised q, filters, cursor)`. Search traffic is Zipf-distributed —
  a small cache absorbs a large share of it.
- The query is `LIMIT`-capped identically to every other list, so a pathological
  `q` cannot return more rows than a normal page.

```sql
SELECT id, prompt, ... FROM assets
 WHERE published AND deleted_at IS NULL AND status = 'READY'
   AND prompt % $1                              -- trigram, uses the GIN index
   AND (published_at, id) < ($2, $3)
 ORDER BY published_at DESC, id DESC
 LIMIT $4;
```

Ranking by recency rather than similarity within the result set is deliberate: on
a creative feed, "new and relevant" reads better than "most similar", and it lets
search share the same keyset cursor as the unfiltered feed.

---

## 13. Caching

| Layer | What | TTL | Invalidation |
|---|---|---|---|
| CDN | Generated frames | 1 year, immutable | never (content-addressed) |
| CDN | `GET /v1/catalog` | 5 min + SWR 1 h | ETag; purge on deploy |
| Redis | Catalog rows | 5 min | key delete on admin write |
| Redis | Search results | 30 s | TTL only |
| Redis | Wall page 1 | 15 s | TTL only |
| Redis | Idempotency responses | 24 h | TTL only |
| Client | Catalog | session | version check on mount |

Only page 1 of the wall is cached. It absorbs the large majority of feed traffic;
deeper pages are long-tail and cheap to serve from the index directly. Personal
data — library, ledger, jobs, `/v1/me` — is `Cache-Control: private, no-store`,
without exception.

---

## 14. Authentication

The design has to preserve a property the current app is right to be proud of:
**a stranger opens the link and gets a working composer with 40 credits.** So
anonymity is a first-class account state, not an absence of one.

- `POST /v1/auth/anonymous` creates a real `User` row with `isAnonymous = true`,
  grants 40 credits with a `SIGNUP_GRANT` ledger entry, and sets two cookies:
  a 15-minute access JWT and a 30-day refresh token. Both `httpOnly`, `Secure`,
  `SameSite=Lax`, `Path=/`.
- Claiming a handle **upgrades the same row**. The work made while anonymous
  stays attached — no migration, no merge, no data loss. This is why the anon
  user is a row and not a cookie blob.
- Refresh tokens are **stored hashed and rotated on use**, with reuse detection:
  a second use of a consumed token revokes the whole session family. A stolen
  refresh token is then good for one request, not thirty days.
- No token in `localStorage`. `httpOnly` cookies are not readable by injected
  script, which is the entire point.
- Anonymous users with no assets and no activity for 30 days are reaped by a
  nightly job. Without that, the `users` table becomes a bot-traffic landfill.

**Abuse note:** free credits per anonymous session is a faucet. Mitigations:
BotID on the anonymous-create route, a `generate`-class limit keyed on hashed IP
*in addition to* user id, and a per-IP cap on anonymous account creation. The
grant is 40 credits — enough to evaluate, not enough to be worth farming.

---

## 15. Observability

- **Structured JSON logs** (`structlog`), one line per request, with
  `request_id`, `user_id`, route, status, duration, and for generation:
  `job_id`, `model_id`, `attempt`, upstream latency. Prompts are **not** logged
  at info level — they are user content.
- **`X-Request-Id`** generated at the BFF, propagated to FastAPI and into worker
  tasks, returned in every response and every problem+json body. One id
  correlates a browser error to a worker log line.
- **OpenTelemetry** traces: FastAPI → Prisma → Redis → upstream, so a slow
  submit is attributable to a specific span rather than guessed at.
- **Metrics that map to the product's promises:**
  `job_duration_seconds` (histogram, by model), `job_outcome_total`
  (by status — the refund rate is a product KPI, not just an error rate),
  `credits_delta_total`, `ledger_drift` (must be 0), `ratelimit_denied_total`
  (by class), `upstream_breaker_state`, `queue_depth`, `sse_connections`.
- **Alerts:** ledger drift ≠ 0 (page immediately — that is money), refund rate
  > 10% over 15 min, queue depth > 500, p95 submit > 500 ms, breaker open > 5 min.

---

## 16. Performance budget

Targets, enforced by a load test in CI against a seeded 100k-asset database. A
regression past these fails the build.

| Endpoint | p50 | p95 | Notes |
|---|---|---|---|
| `GET /v1/catalog` | 5 ms | 20 ms | Redis hit; CDN mostly absorbs it |
| `GET /v1/wall` | 15 ms | 60 ms | One index scan, no joins, no COUNT |
| `GET /v1/wall?q=` | 30 ms | 120 ms | Trigram bitmap scan |
| `GET /v1/library` | 15 ms | 60 ms | Keyset |
| `POST /v1/jobs/quote` | 5 ms | 15 ms | Cached catalog, pure arithmetic |
| `POST /v1/jobs` | 40 ms | 150 ms | One transaction, then enqueue |
| `GET /v1/ledger` | 10 ms | 40 ms | Keyset |

How they are met, concretely:

- **Pooled connections.** Runtime uses the PgBouncer/Neon pooled endpoint;
  migrations use `directUrl`. A serverless Python service against an unpooled
  Postgres exhausts connections at trivial load — this is the single most common
  way this architecture fails in production.
- **No N+1.** Prisma `include` is explicit, and `authorHandle` / `likeCount` are
  denormalised specifically so the feed needs zero joins. The repository layer
  is the only place a query exists, which makes N+1 reviewable.
- **`select` narrow.** The grid does not fetch `composedPrompt`.
- **Counter columns, not aggregates.** `likeCount` is incremented in the same
  transaction as the `Like` insert. `COUNT(*)` on likes for a 24-tile feed is 24
  aggregate queries; a column is free.
- **Keyset everywhere**, so pagination cost is constant in page depth.
- **`gzip`/`br` compression** on JSON responses above 1 KB.
- **`EXPLAIN ANALYZE` in CI** for the seven queries above, asserting no
  `Seq Scan` on `assets` and no `Sort` node on the feed path.

---

## 17. Scaling path

The design is stateless where it counts, which is what makes each step below a
configuration change rather than a rewrite.

1. **Now → 10k assets.** One FastAPI instance, one worker, Neon free tier.
2. **→ 1M assets.** Scale FastAPI horizontally (no in-process state — the reason
   rate limiting and pacing live in Redis and not in a module variable). Worker
   count scales independently; the upstream token bucket already caps aggregate
   outbound rate, so more workers do not mean more upstream pressure.
3. **→ 10M assets.** Read replica for feed and search; writes stay on primary.
   The repository layer routes by intent, so this is one change in `deps.py`.
4. **→ beyond.** Partition `assets` and `ledger_entries` by month
   (`created_at` range). Both are append-mostly and queried by recent window,
   which is exactly the access pattern partitioning rewards. The keyset cursors
   already carry a timestamp, so partition pruning works without a contract
   change.
5. **Hot feed.** If page 1 of the wall becomes the bottleneck, it materialises
   into a Redis sorted set updated on publish. The endpoint contract does not
   change.

What is deliberately *not* built yet: sharding, a search cluster, a CQRS split.
Each would be justified by a metric we do not have.

---

## 18. Migrating the frontend off localStorage

The existing `store.tsx` comment claims swapping persistence for Postgres is "a
change to this file and nothing else." That is nearly true and worth keeping true.

1. **Catalog first.** `catalog.ts` becomes a fetch of `GET /v1/catalog`, typed
   identically. Nothing else moves. Ship it; the app still works.
2. **Anonymous session.** A root-layout effect calls `/v1/auth/anonymous` if no
   cookie. `state.handle` / `state.credits` now come from `/v1/me`.
3. **Reads.** Wall, library and ledger switch from reducer selectors to
   `useInfiniteCursor`. The reducer stops being the source of truth for lists.
4. **Writes.** `useSubmit` posts to `/v1/jobs` with an `Idempotency-Key` and
   stops touching credits. `jobs.tsx` drops the debit/refund logic entirely —
   that code moves to the server, where it belongs, and is *deleted* here rather
   than left as a dead second implementation.
5. **Live updates.** `JobTray` subscribes to `/v1/jobs/stream`.
6. **One-time import.** On first authenticated load, if a `darkroom:v1`
   localStorage blob exists, offer to import it: `POST /v1/import` validates and
   inserts the user's own assets with `seeded = false`, then clears the key. An
   existing visitor does not lose their contact sheet.
7. **`loader.ts` retires.** Client-side queueing and priority were compensating
   for the absence of a server. The server now paces; the client just renders.

Frames keep working throughout, because `/v1/frames/:assetId` is URL-compatible
with what `Frame.tsx` already consumes.

---

## 19. Local development and deployment

```bash
make install         # venv + python deps + npm + migrate + seed
cp .env.example .env

# or step by step
docker compose up -d           # postgres:16.4 + redis:7.4
python3 -m venv api/.venv && api/.venv/bin/pip install -e "api[dev]"
npm run db:migrate:deploy      # wraps `python -m prisma migrate deploy`
npm run db:generate            # regenerate the Python client
npm run db:seed                # catalog + wall, idempotent, validates

make api       # uvicorn --reload            :8000
make worker    # generation worker
make dev       # next                        :3000
make check     # the CI gate: lint + typecheck + test
```

`docker compose up -d` is the documented path and pins both images. Any
reachable Postgres 15+ and Redis 7 will do — set `DATABASE_URL` and `REDIS_URL`
and the migrations replay identically.

`docker compose up` is the whole environment — Postgres and Redis are pinned by
digest so a new contributor gets the same database as CI.

**Deployment.** Next on Vercel. FastAPI and the worker as two containers (Fly.io
or Railway; one process type each, same image). Postgres via Neon, Redis via
Upstash — both reachable from Vercel and from the containers. Object storage on
Vercel Blob.

**Migrations in CI**, never on boot: `prisma migrate deploy` runs as a release
step against `DIRECT_DATABASE_URL` before the new revision takes traffic. Two
instances racing `migrate deploy` on startup is a corrupted schema. Every
migration must be backward-compatible with the previous app version so a rollback
does not require a down-migration — expand/contract, always.

**Config fails fast.** `pydantic-settings` validates every environment variable at
import. A missing `DATABASE_URL` or a `JWT_SECRET` under 32 bytes crashes the
process at boot rather than at the first request.

---

## 20. Testing

| Layer | Tool | What it proves |
|---|---|---|
| Unit | pytest | Pricing arithmetic, cursor round-trip, sanitiser, limiter maths |
| Integration | pytest + testcontainers | Real Postgres and Redis. Every repository query, every constraint |
| Concurrency | pytest-asyncio | 50 parallel submits against 40 credits → exactly the affordable number succeed, ledger sums to zero |
| Idempotency | pytest | Same `Idempotency-Key` twice → one job, one debit |
| Refund | pytest | Forced upstream failure → correct partial refund, run twice → still correct |
| Contract | schemathesis | Fuzzes the OpenAPI schema; no `5xx`, no unvalidated field |
| Schema parity | vitest | Yup and Pydantic agree on every field's bounds and enum set |
| Query plans | pytest | `EXPLAIN` on the seven hot queries: no `Seq Scan`, no `Sort` on feed |
| Load | k6 | 100k-row seed, p95 budget from §16 |
| E2E | Playwright | Compose → job → library → publish → wall → remix, signed out |

The concurrency and refund tests are the ones that matter. Everything else can be
re-derived from the code; correct behaviour under a race cannot.

---

## 21. Lint and type gates

Zero warnings. A warning that is allowed to persist is a warning nobody reads.

```toml
# api/pyproject.toml
[tool.ruff]
target-version = "py312"
line-length = 88
[tool.ruff.lint]
select = ["E","F","I","N","UP","B","A","C4","SIM","ARG","PTH","RUF",
          "S",        # bandit: hardcoded secrets, weak hashes, SQL building
          "ASYNC"]    # blocking calls inside async def
[tool.mypy]
strict = true
disallow_untyped_defs = true
warn_unreachable = true
plugins = ["pydantic.mypy"]
```

- `ruff check --fix` + `ruff format` (replaces black and isort).
- `mypy --strict` over `api/`. Prisma Client Python generates types, so the DB
  boundary is typed rather than `Any`.
- `eslint --max-warnings 0` and `tsc --noEmit` on the frontend.
- `import-linter` enforces the `routers → services → repositories` contract.
- A custom grep gate fails any `query_raw`/`execute_raw` containing an f-string,
  `%` or `+` (§9).
- `pip-audit` and `npm audit --audit-level high`.
- All of the above run as one `make check`, and as the required CI job.

---

## 22. Decisions taken, and what would change them

| Decision | Reason | Revisit when |
|---|---|---|
| Keyset over offset pagination | Constant cost; stable under inserts | Never |
| Prisma schema + Python client | Schema authority is the valuable half | Python client blocks a query we need → SQLAlchemy, same schema |
| Pydantic server-side, Yup client-side | Yup has no Python implementation | Never |
| Credits as `Int` | Credits are discrete; floats do not belong near money | Fractional pricing ships |
| Conditional `UPDATE` over row lock | One atomic statement, no lock contention | Multi-currency or holds/reservations |
| Ledger as append-only truth | Auditable; balance is reconcilable | Never |
| A Redis `BLPOP` loop over ARQ/Celery | One dependency fewer, and the worker stays importable in tests with no broker running. The contract (enqueue after commit, guarded state transition, sweeper for lost messages) is the same | Scheduled fan-out, cron, or multi-broker — then ARQ, which the design already fits |
| SSE over WebSocket | One-directional; works through proxies; no extra infra | Client needs to push |
| Denormalised `authorHandle`, `likeCount` | Feed reads with zero joins | Handles become editable → backfill job |
| Content-addressed storage keys | Free dedupe, honest immutable caching | Never |
| Anonymous users as real rows | Preserves "signed out works" with real enforcement | Never |
| Catalog in Postgres, not code | Pricing changes without a deploy | Never |
| Fail-open limiter, except `generate` | Availability over protection, except for money | Never |

### Rules the product already had, that the server must not tighten

A still accepts **any** preset, including a motion one -- that is the preset's
look without the move, and the seeded wall is full of such pairings. Only the
motion direction is constrained: a motion model needs a preset that carries a
camera move, because the move is the thing being rendered. An earlier version of
`_assert_compatible` required `preset.mode == model.mode`, which silently made
most of the wall un-remixable. The browser test caught it on the first Remix
click; no unit test would have, because the rule looked self-consistent.

### Known gaps, named rather than hidden

- **Billing is still simulated.** `PATCH /v1/me/plan` switches plans and grants
  credits without a payment. Real billing is a Stripe webhook writing
  `PLAN_GRANT` ledger entries — the ledger is already shaped for it, which is the
  point, but it is not built.
- **Motion is still a keyframe plus a browser-rendered camera move.** The README
  is honest about this and stays honest. `services/generation.py` is the single
  swap point for a real video model; the job, ledger and storage model need no
  change to accommodate one.
- **No moderation.** A public wall with freeform prompts needs a review queue.
  The `AuditLog` table and the `AssetStatus` enum leave room for a `QUARANTINED`
  state; the policy does not exist yet.
- **No email.** Handle claiming does not verify ownership, so a handle is a
  display name, not an identity. `emailVerifiedAt` exists for when it must be.
