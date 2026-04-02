-- Add Telegram metadata columns to sources (PostgreSQL).
-- Safe to run once on existing DBs after workspace migration.

BEGIN;

ALTER TABLE sources ADD COLUMN IF NOT EXISTS telegram_title VARCHAR(512);
ALTER TABLE sources ADD COLUMN IF NOT EXISTS telegram_participants_count INTEGER;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS telegram_meta_updated_at TIMESTAMPTZ;

COMMIT;
