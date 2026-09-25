-- The wall feed index now leads on "published", so the filtered feed query is
-- served directly by the index with no separate filter step.
--
-- NOTE: prisma migrate dev also generated `DROP INDEX assets_prompt_trgm_idx`
-- here and it has been deleted by hand. Prisma manages indexes, so any index
-- it cannot express in the DSL (the trigram GIN) shows up as drift and it will
-- propose dropping it on every migrate dev. Always read the generated SQL and
-- remove those lines. See CLAUDE.md, "How to add a migration".

-- DropIndex
DROP INDEX "assets_publishedAt_id_idx";

-- CreateIndex
CREATE INDEX "assets_published_publishedAt_id_idx" ON "assets"("published", "publishedAt" DESC, "id" DESC);
