-- +goose Up
CREATE TABLE consumer_transactions (
  id           TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
  consumer_id  TEXT        NOT NULL REFERENCES consumers(id),
  session_id   TEXT        NOT NULL,
  amount_cents BIGINT      NOT NULL,
  currency     TEXT        NOT NULL DEFAULT 'usd',
  status       TEXT        NOT NULL CHECK (status IN ('pending','completed','failed')),
  plain_label  TEXT        NOT NULL,
  merchant_id  TEXT        NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX consumer_transactions_consumer_idx
  ON consumer_transactions (consumer_id, created_at DESC);

-- +goose Down
DROP TABLE consumer_transactions;
