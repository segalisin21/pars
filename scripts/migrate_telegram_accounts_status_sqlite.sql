-- Telegram accounts: status metadata for UI (username + @SpamBot snapshot).
-- SQLite supports ADD COLUMN (no IF NOT EXISTS prior to 3.35); run once.
alter table telegram_accounts add column last_username text;
alter table telegram_accounts add column spambot_status_text text;
alter table telegram_accounts add column spambot_checked_at text;
alter table telegram_accounts add column spambot_error text;

