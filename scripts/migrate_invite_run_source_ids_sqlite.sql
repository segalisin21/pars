-- SQLite: add invite_runs.source_ids as JSON text (SQLAlchemy JSON maps to TEXT).
-- Run manually if upgrading an existing file-based SQLite DB (not create_all).

ALTER TABLE invite_runs ADD COLUMN source_ids TEXT NOT NULL DEFAULT '[]';
