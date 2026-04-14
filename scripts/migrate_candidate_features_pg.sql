-- Candidate targeting features (Postgres).
CREATE TABLE IF NOT EXISTS candidate_features (
  id SERIAL PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  candidate_id INTEGER NOT NULL REFERENCES candidate_users(id),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  source_count INTEGER NOT NULL DEFAULT 0,
  source_priority_score INTEGER NOT NULL DEFAULT 0,
  seen_as VARCHAR(16) NOT NULL DEFAULT 'participants',
  has_username BOOLEAN NOT NULL DEFAULT FALSE,
  has_display_name BOOLEAN NOT NULL DEFAULT FALSE,
  topic_keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
  intent_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  warmth_score INTEGER NOT NULL DEFAULT 0,
  risk_score INTEGER NOT NULL DEFAULT 0,
  send_score INTEGER NOT NULL DEFAULT 0,
  segment VARCHAR(8) NOT NULL DEFAULT 'C',
  reasons JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT uq_candidate_features_ws_candidate UNIQUE (workspace_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS ix_candidate_features_ws_segment_score
  ON candidate_features (workspace_id, segment, send_score);

