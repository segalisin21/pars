-- Per-source collect strategy (PostgreSQL).
BEGIN;

ALTER TABLE sources ADD COLUMN IF NOT EXISTS collect_mode VARCHAR(32) NOT NULL DEFAULT 'participants';

COMMIT;
