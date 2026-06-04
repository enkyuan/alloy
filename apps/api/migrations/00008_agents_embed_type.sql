-- +goose Up
ALTER TABLE agents
  ADD COLUMN embed_type TEXT NOT NULL DEFAULT 'widget'
    CHECK (embed_type IN ('widget', 'webhook'));

-- +goose Down
ALTER TABLE agents DROP COLUMN embed_type;
