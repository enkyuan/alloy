-- Canonical v1 contract for a durable Kaji backend. Implementations may add
-- storage details but must preserve the constraints and idempotency semantics.

CREATE TABLE kaji_events (
    session_id TEXT NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence >= 0),
    event_id TEXT NOT NULL,
    event_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, sequence),
    UNIQUE (event_id)
);

CREATE TABLE kaji_tool_idempotency (
    session_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'unknown')),
    result_json JSONB,
    error_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, tool_call_id)
);

-- fingerprint = SHA-256(canonical JSON [tool_name, tool_args]), where canonical
-- JSON uses sorted keys, compact separators, UTF-8 characters, and rejects NaN.
-- State transitions: running -> completed | unknown. A retryable failure deletes
-- its running claim; no timeout may reclaim a running row as a safe terminal state.
