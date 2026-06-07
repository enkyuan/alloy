-- +goose Up
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE users (
    id          TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    email       CITEXT      NOT NULL UNIQUE,
    name        TEXT        NOT NULL DEFAULT '',
    avatar_url  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX users_email_idx ON users (email);

-- +goose Down
DROP TABLE users;
