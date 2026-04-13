-- Add optional MTProto cloud message id on broadcast_deliveries (SQLite).
ALTER TABLE broadcast_deliveries ADD COLUMN telegram_message_id INTEGER NULL;
