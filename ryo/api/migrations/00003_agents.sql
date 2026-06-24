-- +goose Up
CREATE TABLE agents (
    id            TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    org_id        TEXT        NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name          TEXT        NOT NULL,
    business_type TEXT        NOT NULL DEFAULT 'custom',
    system_prompt TEXT        NOT NULL DEFAULT '',
    tools         TEXT[]      NOT NULL DEFAULT '{}',
    voice_enabled BOOLEAN     NOT NULL DEFAULT false,
    wallet_id     TEXT,
    embed_token   TEXT        NOT NULL DEFAULT gen_random_uuid()::text,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX agents_org_idx ON agents (org_id);

-- +goose Down
DROP TABLE agents;
