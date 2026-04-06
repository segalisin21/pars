-- SQLite: global Telegram accounts + optional FK on collect/invite runs.

CREATE TABLE IF NOT EXISTS telegram_accounts (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    label VARCHAR(128) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT 1,
    session_string_encrypted VARCHAR(8192) NOT NULL,
    session_string_key_version INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL,
    last_used_at DATETIME,
    last_ok_at DATETIME,
    last_error_code VARCHAR(64),
    last_error_at DATETIME,
    cooldown_until DATETIME
);

-- If upgrading an existing SQLite file (not fresh create_all), run once:
-- ALTER TABLE collect_runs ADD COLUMN telegram_account_id INTEGER;
-- ALTER TABLE invite_runs ADD COLUMN telegram_account_id INTEGER;
