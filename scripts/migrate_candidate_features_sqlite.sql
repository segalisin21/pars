-- Candidate targeting features (SQLite).
CREATE TABLE IF NOT EXISTS candidate_features (
  id INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL,
  candidate_id INTEGER NOT NULL,
  computed_at TEXT NOT NULL,
  source_count INTEGER NOT NULL DEFAULT 0,
  source_priority_score INTEGER NOT NULL DEFAULT 0,
  seen_as TEXT NOT NULL DEFAULT 'participants',
  has_username INTEGER NOT NULL DEFAULT 0,
  has_display_name INTEGER NOT NULL DEFAULT 0,
  topic_keywords TEXT NOT NULL DEFAULT '[]',
  intent_flags TEXT NOT NULL DEFAULT '[]',
  warmth_score INTEGER NOT NULL DEFAULT 0,
  risk_score INTEGER NOT NULL DEFAULT 0,
  send_score INTEGER NOT NULL DEFAULT 0,
  segment TEXT NOT NULL DEFAULT 'C',
  reasons TEXT NOT NULL DEFAULT '{}',
  UNIQUE (workspace_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS ix_candidate_features_ws_segment_score
  ON candidate_features (workspace_id, segment, send_score);

