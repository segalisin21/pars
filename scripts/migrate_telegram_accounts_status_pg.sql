-- Telegram accounts: status metadata for UI (username + @SpamBot snapshot).
alter table telegram_accounts add column if not exists last_username varchar(64);
alter table telegram_accounts add column if not exists spambot_status_text text;
alter table telegram_accounts add column if not exists spambot_checked_at timestamptz;
alter table telegram_accounts add column if not exists spambot_error varchar(128);

