-- Add InviteRun.source_ids (JSONB) for filtering candidates by collection sources.
-- Empty array = all workspace candidates (backward compatible).
--
-- Run: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/migrate_invite_run_source_ids_pg.sql

ALTER TABLE invite_runs
  ADD COLUMN IF NOT EXISTS source_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
