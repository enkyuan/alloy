-- +goose Up
-- Tracks every Stripe event we have already processed end-to-end.
-- Stripe delivers at-least-once: network blips, our own 5xx responses, and
-- Stripe replays can all cause the same event.ID to arrive multiple times.
-- Inserting into this table inside the same tx as the session update + the
-- webhook delivery enqueue makes the whole "apply this Stripe event" atomic
-- AND idempotent.
CREATE TABLE processed_stripe_events (
  event_id     TEXT        PRIMARY KEY,
  event_type   TEXT        NOT NULL,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE processed_stripe_events;
