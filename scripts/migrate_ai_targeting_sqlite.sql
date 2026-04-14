-- AI targeting profiles + candidate messages/embeddings (SQLite).

CREATE TABLE IF NOT EXISTS targeting_profiles (
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  query TEXT NOT NULL DEFAULT '',
  language_mode TEXT NOT NULL DEFAULT 'mixed',
  params TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_targeting_profiles_ws ON targeting_profiles (workspace_id);

CREATE TABLE IF NOT EXISTS candidate_messages (
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL,
  source_id INTEGER NOT NULL,
  candidate_id INTEGER NOT NULL,
  msg_date TEXT NULL,
  text TEXT NOT NULL DEFAULT '',
  text_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (workspace_id, candidate_id, text_hash)
);

CREATE INDEX IF NOT EXISTS ix_candidate_messages_ws_candidate_date
  ON candidate_messages (workspace_id, candidate_id, msg_date);

CREATE TABLE IF NOT EXISTS candidate_embeddings (
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL,
  candidate_id INTEGER NOT NULL,
  model TEXT NOT NULL DEFAULT 'text-embedding-3-small',
  vector TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL,
  UNIQUE (workspace_id, candidate_id)
);

