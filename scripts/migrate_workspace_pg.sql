-- One-time migration: legacy single-tenant schema -> workspace-scoped schema (PostgreSQL).
-- Symptom after deploy: GET /sources, /collect-runs return 503 (DBAPIError: missing column workspace_id).
--
-- Run against Railway Postgres (Query tab or psql):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/migrate_workspace_pg.sql
--
-- Backup the database before running in production.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) workspaces + default tenant id = 1
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workspaces (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO workspaces (id, name)
SELECT 1, 'default'
WHERE NOT EXISTS (SELECT 1 FROM workspaces WHERE id = 1);

SELECT setval(
    pg_get_serial_sequence('workspaces', 'id'),
    GREATEST((SELECT COALESCE(MAX(id), 1) FROM workspaces), 1)
);

-- ---------------------------------------------------------------------------
-- 2) sources
-- ---------------------------------------------------------------------------
ALTER TABLE sources ADD COLUMN IF NOT EXISTS workspace_id INTEGER;
UPDATE sources SET workspace_id = 1 WHERE workspace_id IS NULL;
ALTER TABLE sources ALTER COLUMN workspace_id SET NOT NULL;

ALTER TABLE sources DROP CONSTRAINT IF EXISTS uq_source_type_identifier;

DO $$ BEGIN
  ALTER TABLE sources
    ADD CONSTRAINT sources_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE sources ADD CONSTRAINT uq_source_workspace_type_identifier UNIQUE (workspace_id, type, identifier);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_sources_workspace_id ON sources (workspace_id);

-- ---------------------------------------------------------------------------
-- 3) invite_targets
-- ---------------------------------------------------------------------------
ALTER TABLE invite_targets ADD COLUMN IF NOT EXISTS workspace_id INTEGER;
UPDATE invite_targets SET workspace_id = 1 WHERE workspace_id IS NULL;
ALTER TABLE invite_targets ALTER COLUMN workspace_id SET NOT NULL;

ALTER TABLE invite_targets DROP CONSTRAINT IF EXISTS invite_targets_identifier_key;
ALTER TABLE invite_targets DROP CONSTRAINT IF EXISTS uq_invite_targets_identifier;

DO $$ BEGIN
  ALTER TABLE invite_targets
    ADD CONSTRAINT invite_targets_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE invite_targets ADD CONSTRAINT uq_target_workspace_identifier UNIQUE (workspace_id, identifier);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_invite_targets_workspace_id ON invite_targets (workspace_id);

-- ---------------------------------------------------------------------------
-- 4) candidate_users (must be before candidate_source_links backfill from candidates)
-- ---------------------------------------------------------------------------
ALTER TABLE candidate_users ADD COLUMN IF NOT EXISTS workspace_id INTEGER;
UPDATE candidate_users SET workspace_id = 1 WHERE workspace_id IS NULL;
ALTER TABLE candidate_users ALTER COLUMN workspace_id SET NOT NULL;

ALTER TABLE candidate_users DROP CONSTRAINT IF EXISTS uq_candidate_tg_user_id;
ALTER TABLE candidate_users DROP CONSTRAINT IF EXISTS uq_candidate_username;

DO $$ BEGIN
  ALTER TABLE candidate_users
    ADD CONSTRAINT candidate_users_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE candidate_users ADD CONSTRAINT uq_candidate_workspace_tg_user_id UNIQUE (workspace_id, tg_user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE candidate_users ADD CONSTRAINT uq_candidate_workspace_username UNIQUE (workspace_id, username);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_candidate_users_workspace_id ON candidate_users (workspace_id);

-- ---------------------------------------------------------------------------
-- 5) candidate_source_links
-- ---------------------------------------------------------------------------
ALTER TABLE candidate_source_links ADD COLUMN IF NOT EXISTS workspace_id INTEGER;

UPDATE candidate_source_links csl
SET workspace_id = cu.workspace_id
FROM candidate_users cu
WHERE csl.candidate_id = cu.id AND csl.workspace_id IS NULL;

UPDATE candidate_source_links SET workspace_id = 1 WHERE workspace_id IS NULL;

ALTER TABLE candidate_source_links ALTER COLUMN workspace_id SET NOT NULL;

ALTER TABLE candidate_source_links DROP CONSTRAINT IF EXISTS uq_candidate_source;

DO $$ BEGIN
  ALTER TABLE candidate_source_links
    ADD CONSTRAINT candidate_source_links_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE candidate_source_links ADD CONSTRAINT uq_candidate_source_workspace UNIQUE (workspace_id, candidate_id, source_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_candidate_source_links_workspace_id ON candidate_source_links (workspace_id);

-- ---------------------------------------------------------------------------
-- 6) suppression_list
-- ---------------------------------------------------------------------------
ALTER TABLE suppression_list ADD COLUMN IF NOT EXISTS workspace_id INTEGER;
UPDATE suppression_list SET workspace_id = 1 WHERE workspace_id IS NULL;
ALTER TABLE suppression_list ALTER COLUMN workspace_id SET NOT NULL;

DO $$ BEGIN
  ALTER TABLE suppression_list
    ADD CONSTRAINT suppression_list_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_suppression_list_workspace_id ON suppression_list (workspace_id);

-- ---------------------------------------------------------------------------
-- 7) collect_runs
-- ---------------------------------------------------------------------------
ALTER TABLE collect_runs ADD COLUMN IF NOT EXISTS workspace_id INTEGER;
UPDATE collect_runs SET workspace_id = 1 WHERE workspace_id IS NULL;
ALTER TABLE collect_runs ALTER COLUMN workspace_id SET NOT NULL;

DO $$ BEGIN
  ALTER TABLE collect_runs
    ADD CONSTRAINT collect_runs_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_collect_runs_workspace_id ON collect_runs (workspace_id);

-- ---------------------------------------------------------------------------
-- 8) invite_runs (before invite_attempts)
-- ---------------------------------------------------------------------------
ALTER TABLE invite_runs ADD COLUMN IF NOT EXISTS workspace_id INTEGER;
UPDATE invite_runs SET workspace_id = 1 WHERE workspace_id IS NULL;
ALTER TABLE invite_runs ALTER COLUMN workspace_id SET NOT NULL;

DO $$ BEGIN
  ALTER TABLE invite_runs
    ADD CONSTRAINT invite_runs_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_invite_runs_workspace_id ON invite_runs (workspace_id);

-- ---------------------------------------------------------------------------
-- 9) invite_attempts
-- ---------------------------------------------------------------------------
ALTER TABLE invite_attempts ADD COLUMN IF NOT EXISTS workspace_id INTEGER;

UPDATE invite_attempts ia
SET workspace_id = ir.workspace_id
FROM invite_runs ir
WHERE ia.invite_run_id = ir.id AND ia.workspace_id IS NULL;

UPDATE invite_attempts SET workspace_id = 1 WHERE workspace_id IS NULL;

ALTER TABLE invite_attempts ALTER COLUMN workspace_id SET NOT NULL;

DO $$ BEGIN
  ALTER TABLE invite_attempts
    ADD CONSTRAINT invite_attempts_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_invite_attempts_workspace_id ON invite_attempts (workspace_id);

-- ---------------------------------------------------------------------------
-- 10) audit_events
-- ---------------------------------------------------------------------------
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS workspace_id INTEGER;
UPDATE audit_events SET workspace_id = 1 WHERE workspace_id IS NULL;
ALTER TABLE audit_events ALTER COLUMN workspace_id SET NOT NULL;

DO $$ BEGIN
  ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES workspaces (id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_audit_events_workspace_id ON audit_events (workspace_id);

COMMIT;
