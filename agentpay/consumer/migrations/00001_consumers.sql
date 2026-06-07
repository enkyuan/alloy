-- +goose Up
CREATE TABLE consumers (
  id                 TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
  email              TEXT        NOT NULL UNIQUE,
  hashed_password    TEXT        NOT NULL,
  stripe_customer_id TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE consumers;
