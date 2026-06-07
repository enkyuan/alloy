-- +goose Up
CREATE TABLE webhooks (
  id         TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
  org_id     TEXT        NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  url        TEXT        NOT NULL,
  secret     TEXT        NOT NULL,
  events     TEXT[]      NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE webhook_deliveries (
  id           TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
  webhook_id   TEXT        NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
  event_type   TEXT        NOT NULL,
  payload      JSONB       NOT NULL,
  status       TEXT        NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'delivered', 'failed', 'dead')),
  attempts     INT         NOT NULL DEFAULT 0,
  next_attempt TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_status  INT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX webhooks_org_idx ON webhooks (org_id);
CREATE INDEX webhook_deliveries_pending_idx
  ON webhook_deliveries (next_attempt)
  WHERE status = 'pending';

-- +goose Down
DROP TABLE webhook_deliveries;
DROP TABLE webhooks;
