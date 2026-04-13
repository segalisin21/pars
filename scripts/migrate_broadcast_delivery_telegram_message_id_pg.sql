-- Add optional MTProto cloud message id on broadcast_deliveries (Postgres).
ALTER TABLE broadcast_deliveries
  ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT NULL;
