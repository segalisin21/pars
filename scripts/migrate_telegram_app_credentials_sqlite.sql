-- Telegram app credentials (api_id/api_hash) stored encrypted at rest.
create table if not exists telegram_app_credentials (
  id integer primary key,
  api_id_encrypted text not null default '',
  api_hash_encrypted text not null default '',
  key_version integer not null default 1,
  updated_at text not null default (datetime('now'))
);

