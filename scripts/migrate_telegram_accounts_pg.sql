-- One-time migration: global Telegram accounts + optional FK on collect/invite runs.
-- Run against the same DATABASE_URL as api/worker.

CREATE TABLE IF NOT EXISTS telegram_accounts (
    id SERIAL PRIMARY KEY,
    label VARCHAR(128) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    session_string_encrypted VARCHAR(8192) NOT NULL,
    session_string_key_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    last_ok_at TIMESTAMPTZ,
    last_error_code VARCHAR(64),
    last_error_at TIMESTAMPTZ,
    cooldown_until TIMESTAMPTZ
);

ALTER TABLE collect_runs
    ADD COLUMN IF NOT EXISTS telegram_account_id INTEGER REFERENCES telegram_accounts(id);

CREATE INDEX IF NOT EXISTS ix_collect_runs_telegram_account_id ON collect_runs(telegram_account_id);

ALTER TABLE invite_runs
    ADD COLUMN IF NOT EXISTS telegram_account_id INTEGER REFERENCES telegram_accounts(id);

CREATE INDEX IF NOT EXISTS ix_invite_runs_telegram_account_id ON invite_runs(telegram_account_id);
