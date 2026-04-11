-- Broadcast DM runs + per-recipient log; partial unique: one successful send per (workspace, message_key, tg_user_id).
-- Run against the same DATABASE_URL as api/worker.

CREATE TABLE IF NOT EXISTS broadcast_runs (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    telegram_account_id INTEGER REFERENCES telegram_accounts(id),
    message_key VARCHAR(128) NOT NULL,
    message_body TEXT NOT NULL,
    source_ids JSON NOT NULL DEFAULT '[]',
    candidate_ids JSON NOT NULL DEFAULT '[]',
    policy JSON NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    stats JSON NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS ix_broadcast_runs_workspace_id ON broadcast_runs (workspace_id);
CREATE INDEX IF NOT EXISTS ix_broadcast_runs_message_key ON broadcast_runs (message_key);
CREATE INDEX IF NOT EXISTS ix_broadcast_runs_telegram_account_id ON broadcast_runs (telegram_account_id);

CREATE TABLE IF NOT EXISTS broadcast_deliveries (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    broadcast_run_id INTEGER NOT NULL REFERENCES broadcast_runs(id),
    message_key VARCHAR(128) NOT NULL,
    candidate_id INTEGER NOT NULL REFERENCES candidate_users(id),
    tg_user_id BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL,
    error_code VARCHAR(64),
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_broadcast_deliveries_workspace_id ON broadcast_deliveries (workspace_id);
CREATE INDEX IF NOT EXISTS ix_broadcast_deliveries_broadcast_run_id ON broadcast_deliveries (broadcast_run_id);
CREATE INDEX IF NOT EXISTS ix_broadcast_deliveries_message_key ON broadcast_deliveries (message_key);
CREATE INDEX IF NOT EXISTS ix_broadcast_deliveries_candidate_id ON broadcast_deliveries (candidate_id);
CREATE INDEX IF NOT EXISTS ix_broadcast_deliveries_tg_user_id ON broadcast_deliveries (tg_user_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_broadcast_delivery_success_ws_key_tg
ON broadcast_deliveries (workspace_id, message_key, tg_user_id)
WHERE status = 'success';
