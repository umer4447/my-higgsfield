-- Extension creation gets a migration of its own. The Prisma migration runner
-- silently stops executing a file after CREATE EXTENSION: later statements are
-- skipped with no error and the migration still reports success. Keeping this
-- alone makes that behaviour harmless.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
