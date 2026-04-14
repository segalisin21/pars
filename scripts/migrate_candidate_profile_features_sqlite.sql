-- Per-profile candidate scoring (SQLite).

CREATE TABLE IF NOT EXISTS candidate_profile_features (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
  candidate_id INTEGER NOT NULL REFERENCES candidate_users(id),
  targeting_profile_id INTEGER NOT NULL REFERENCES targeting_profiles(id),
  computed_at DATETIME NOT NULL,
  source_count INTEGER NOT NULL DEFAULT 0,
  source_priority_score INTEGER NOT NULL DEFAULT 0,
  seen_as TEXT NOT NULL DEFAULT 'participants',
  has_username BOOLEAN NOT NULL DEFAULT 0,
  has_display_name BOOLEAN NOT NULL DEFAULT 0,
  topic_keywords JSON NOT NULL DEFAULT '[]',
  intent_flags JSON NOT NULL DEFAULT '[]',
  semantic_score INTEGER NOT NULL DEFAULT 0,
  warmth_score INTEGER NOT NULL DEFAULT 0,
  risk_score INTEGER NOT NULL DEFAULT 0,
  send_score INTEGER NOT NULL DEFAULT 0,
  segment TEXT NOT NULL DEFAULT 'C',
  reasons JSON NOT NULL DEFAULT '{}',
  UNIQUE (workspace_id, candidate_id, targeting_profile_id)
);

CREATE INDEX IF NOT EXISTS ix_candidate_profile_features_ws ON candidate_profile_features (workspace_id);
CREATE INDEX IF NOT EXISTS ix_candidate_profile_features_ws_profile_score
  ON candidate_profile_features (workspace_id, targeting_profile_id, send_score);
CREATE INDEX IF NOT EXISTS ix_candidate_profile_features_ws_profile_segment_score
  ON candidate_profile_features (workspace_id, targeting_profile_id, segment, send_score);

