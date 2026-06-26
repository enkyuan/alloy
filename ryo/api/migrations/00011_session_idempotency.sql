-- +goose Up
-- Idempotency-Key support for POST /v1/sessions.
--
-- The agent runtime (kaji) calls request_payment from inside a tool loop
-- that may retry the same payment on network blips. Without an idempotency
-- key, each retry creates a new Stripe PaymentIntent and a new sessions
-- row, risking double-charge if the customer confirms either.
--
-- Convention: clients send Idempotency-Key on POST /v1/sessions. The
-- handler returns the previously-created session on key collision and
-- passes the same key through to Stripe's PaymentIntent.create.
ALTER TABLE sessions ADD COLUMN idempotency_key TEXT;
CREATE UNIQUE INDEX sessions_idempotency_key_uq
  ON sessions (idempotency_key) WHERE idempotency_key IS NOT NULL;

-- +goose Down
DROP INDEX sessions_idempotency_key_uq;
ALTER TABLE sessions DROP COLUMN idempotency_key;
