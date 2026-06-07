-- +goose Up
CREATE TABLE sessions (
    id             TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    agent_id       TEXT        NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    status         TEXT        NOT NULL DEFAULT 'active',
    amount_collected_cents BIGINT NOT NULL DEFAULT 0,
    currency       TEXT        NOT NULL DEFAULT 'usd',
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at       TIMESTAMPTZ
);

CREATE TABLE session_events (
    id         TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    session_id TEXT        NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id   TEXT        NOT NULL,
    kind       TEXT        NOT NULL,
    payload    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX sessions_agent_idx      ON sessions       (agent_id);
CREATE INDEX session_events_sess_idx ON session_events (session_id);

-- +goose Down
DROP TABLE session_events;
DROP TABLE sessions;
