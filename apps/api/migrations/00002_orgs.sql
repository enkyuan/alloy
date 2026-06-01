-- +goose Up
CREATE TABLE orgs (
    id         TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name       TEXT        NOT NULL,
    slug       TEXT        NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE org_members (
    org_id     TEXT        NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    user_id    TEXT        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role       TEXT        NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

CREATE INDEX org_members_user_idx ON org_members (user_id);

-- +goose Down
DROP TABLE org_members;
DROP TABLE orgs;
