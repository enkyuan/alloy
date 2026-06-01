-- +goose Up
CREATE TABLE payment_configs (
    id                     TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    agent_id               TEXT        NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    provider               TEXT        NOT NULL,
    collection_method      TEXT        NOT NULL,
    provider_account_id    TEXT,
    api_key_encrypted      BYTEA,
    require_confirmation   BOOLEAN     NOT NULL DEFAULT true,
    max_auto_charge_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    currency               TEXT        NOT NULL DEFAULT 'usd',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX payment_configs_agent_idx ON payment_configs (agent_id);

-- +goose Down
DROP TABLE payment_configs;
