-- Targeting runs + logs (Postgres).

CREATE TABLE IF NOT EXISTS targeting_runs (
  id SERIAL PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  profile_id INTEGER NOT NULL REFERENCES targeting_profiles(id),
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  stage VARCHAR(32) NOT NULL DEFAULT 'queued',
  progress JSONB NOT NULL DEFAULT '{}'::jsonb,
  error JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at TIMESTAMPTZ NULL,
  finished_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_targeting_runs_ws ON targeting_runs (workspace_id);
CREATE INDEX IF NOT EXISTS ix_targeting_runs_ws_profile ON targeting_runs (workspace_id, profile_id);

CREATE TABLE IF NOT EXISTS targeting_run_logs (
  id SERIAL PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  run_id INTEGER NOT NULL REFERENCES targeting_runs(id),
  msg VARCHAR(512) NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_targeting_run_logs_ws ON targeting_run_logs (workspace_id);
CREATE INDEX IF NOT EXISTS ix_targeting_run_logs_run ON targeting_run_logs (run_id, id);

