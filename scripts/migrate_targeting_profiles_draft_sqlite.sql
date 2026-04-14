-- Draft params for targeting profiles (SQLite).

ALTER TABLE targeting_profiles ADD COLUMN draft_params JSON NULL;
ALTER TABLE targeting_profiles ADD COLUMN draft_updated_at DATETIME NULL;

