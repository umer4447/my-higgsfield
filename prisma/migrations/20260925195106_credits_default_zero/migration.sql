-- Credits default to 0 instead of the signup grant, so a balance can only ever
-- arrive through a LedgerEntry and `credits == SUM(ledger.delta)` is
-- structurally true. A row created directly used to be born in drift.
--
-- NOTE: prisma migrate dev also emitted `DROP INDEX assets_prompt_trgm_idx`
-- here; deleted by hand. Prisma treats any index it cannot express in the DSL
-- as drift and proposes dropping it on every run. See CLAUDE.md.

-- AlterTable
ALTER TABLE "users" ALTER COLUMN "credits" SET DEFAULT 0;
