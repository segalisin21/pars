-- Draft params for targeting profiles (Postgres).

ALTER TABLE targeting_profiles
  ADD COLUMN IF NOT EXISTS draft_params JSONB NULL;

ALTER TABLE targeting_profiles
  ADD COLUMN IF NOT EXISTS draft_updated_at TIMESTAMPTZ NULL;

