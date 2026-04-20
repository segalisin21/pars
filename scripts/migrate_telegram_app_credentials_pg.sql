-- Telegram app credentials (api_id/api_hash) stored encrypted at rest.
create table if not exists telegram_app_credentials (
  id integer primary key,
  api_id_encrypted varchar(1024) not null default '',
  api_hash_encrypted varchar(1024) not null default '',
  key_version integer not null default 1,
  updated_at timestamptz not null default now()
);

