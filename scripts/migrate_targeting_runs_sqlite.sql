-- Targeting runs + logs (SQLite).

CREATE TABLE IF NOT EXISTS targeting_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  profile_id INTEGER NOT NULL REFERENCES targeting_profiles(id),
  status TEXT NOT NULL DEFAULT 'queued',
  stage TEXT NOT NULL DEFAULT 'queued',
  progress JSON NOT NULL DEFAULT '{}',
  error JSON NOT NULL DEFAULT '{}',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  started_at DATETIME NULL,
  finished_at DATETIME NULL
);

CREATE INDEX IF NOT EXISTS ix_targeting_runs_ws ON targeting_runs (workspace_id);
CREATE INDEX IF NOT EXISTS ix_targeting_runs_ws_profile ON targeting_runs (workspace_id, profile_id);

CREATE TABLE IF NOT EXISTS targeting_run_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  run_id INTEGER NOT NULL REFERENCES targeting_runs(id),
  msg TEXT NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_targeting_run_logs_ws ON targeting_run_logs (workspace_id);
CREATE INDEX IF NOT EXISTS ix_targeting_run_logs_run ON targeting_run_logs (run_id, id);

