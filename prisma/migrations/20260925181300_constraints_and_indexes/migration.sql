-- Things the Prisma DSL cannot express. Reviewed as code: this is what runs
-- against production data. See architecture.md section 5, skills.md section 3.
--
-- WARNING: no apostrophes or quote characters in comments in this file.
-- The Prisma migration runner splits statements without excluding `--`
-- comments from its string-literal state machine, so a stray apostrophe
-- silently swallows every statement after it. That is not an error; the
-- migration reports success and the objects are simply absent. Verified the
-- hard way. There is a test for it: tests/test_migrations.py.

-- 1. Credits can never go negative. The last line of defence on the money
--    path: even a logic bug cannot produce a negative balance.
--    Prisma does not model CHECK constraints, so it never drops this.
ALTER TABLE "users"
  ADD CONSTRAINT "users_credits_non_negative" CHECK ("credits" >= 0);

-- 2. Refunds may never exceed what was charged.
ALTER TABLE "jobs"
  ADD CONSTRAINT "jobs_refund_within_debit"
  CHECK ("creditsRefunded" >= 0 AND "creditsRefunded" <= "creditsDebited");

-- 3. A preset that discards the prompt typed by the user is a silent product
--    bug, not a cosmetic one. The template must carry the substitution slot.
ALTER TABLE "presets"
  ADD CONSTRAINT "presets_template_has_slot"
  CHECK ("template" LIKE '%{prompt}%');

-- 4. A batch is bounded at the database, not only in Pydantic.
ALTER TABLE "jobs"
  ADD CONSTRAINT "jobs_batch_bounded" CHECK ("batch" >= 1 AND "batch" <= 8);
