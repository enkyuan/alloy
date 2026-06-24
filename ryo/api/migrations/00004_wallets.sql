-- +goose Up
CREATE TABLE wallets (
    id              TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    org_id          TEXT        NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    provider        TEXT        NOT NULL DEFAULT 'natural',
    external_id     TEXT,
    status          TEXT        NOT NULL DEFAULT 'pending',
    balance_cents   BIGINT      NOT NULL DEFAULT 0,
    currency        TEXT        NOT NULL DEFAULT 'usd',
    kyb_required    BOOLEAN     NOT NULL DEFAULT false,
    kyb_portal_url  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX wallets_org_idx ON wallets (org_id);

ALTER TABLE agents
    ADD CONSTRAINT agents_wallet_fk
    FOREIGN KEY (wallet_id) REFERENCES wallets(id) ON DELETE SET NULL;

-- +goose Down
ALTER TABLE agents DROP CONSTRAINT agents_wallet_fk;
DROP TABLE wallets;
