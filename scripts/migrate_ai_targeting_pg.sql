-- AI targeting profiles + candidate messages/embeddings (Postgres).

CREATE TABLE IF NOT EXISTS targeting_profiles (
  id SERIAL PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  name VARCHAR(128) NOT NULL DEFAULT '',
  query VARCHAR(512) NOT NULL DEFAULT '',
  language_mode VARCHAR(16) NOT NULL DEFAULT 'mixed',
  params JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_targeting_profiles_ws ON targeting_profiles (workspace_id);

CREATE TABLE IF NOT EXISTS candidate_messages (
  id SERIAL PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  source_id INTEGER NOT NULL REFERENCES sources(id),
  candidate_id INTEGER NOT NULL REFERENCES candidate_users(id),
  msg_date TIMESTAMPTZ NULL,
  text TEXT NOT NULL DEFAULT '',
  text_hash VARCHAR(64) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_candidate_messages_ws_candidate_hash UNIQUE (workspace_id, candidate_id, text_hash)
);

CREATE INDEX IF NOT EXISTS ix_candidate_messages_ws_candidate_date
  ON candidate_messages (workspace_id, candidate_id, msg_date);

CREATE TABLE IF NOT EXISTS candidate_embeddings (
  id SERIAL PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  candidate_id INTEGER NOT NULL REFERENCES candidate_users(id),
  model VARCHAR(64) NOT NULL DEFAULT 'text-embedding-3-small',
  vector JSONB NOT NULL DEFAULT '[]'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_candidate_embeddings_ws_candidate UNIQUE (workspace_id, candidate_id)
);

