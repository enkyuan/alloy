-- +goose Up
ALTER TABLE sessions
  ADD COLUMN channel                    TEXT NOT NULL DEFAULT 'chat'
    CHECK (channel IN ('chat', 'voice', 'sms')),
  ADD COLUMN plain_summary              TEXT,
  ADD COLUMN stripe_payment_intent_id   TEXT,
  ADD COLUMN consumer_stripe_customer_id TEXT;

-- +goose Down
ALTER TABLE sessions
  DROP COLUMN channel,
  DROP COLUMN plain_summary,
  DROP COLUMN stripe_payment_intent_id,
  DROP COLUMN consumer_stripe_customer_id;
