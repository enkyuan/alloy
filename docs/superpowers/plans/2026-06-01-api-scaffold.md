# API Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the `@ryo/api` Go service with a real Postgres/Redis store layer, JWT auth middleware, database migrations, and all handler TODO stubs replaced with live queries.

**Architecture:** A shared `internal/store` package initializes and holds the pgx pool and Redis client, injected into each handler domain via a `Store` struct. Auth middleware validates better-auth JWTs and injects `userID`/`orgID` into every request context. Goose handles SQL migrations in `migrations/`. Each handler package gets its own `store.go` with typed query functions, keeping SQL close to the domain it serves.

**Tech Stack:** Go 1.25, pgx/v5, go-redis/v9, golang-jwt/v5, pressly/goose/v3, go-playground/validator/v10, chi/v5

---

## File Map

**New files:**
- `internal/store/store.go` — `Store` struct holding DB pool + Redis client; `New()`, `Close()`
- `internal/store/db.go` — pgx pool init from `DATABASE_URL`
- `internal/store/redis.go` — go-redis client init from `REDIS_URL`
- `internal/middleware/auth.go` — JWT validation middleware; `UserID`/`OrgID` context helpers
- `internal/middleware/validate.go` — request body decode+validate helper
- `migrations/00001_users.sql` — users table
- `migrations/00002_orgs.sql` — orgs table + org_members join
- `migrations/00003_agents.sql` — agents table
- `migrations/00004_wallets.sql` — wallets table
- `migrations/00005_payment_configs.sql` — payment_configs table
- `migrations/00006_sessions.sql` — sessions + session_events tables
- `cmd/migrate/main.go` — standalone `go run ./cmd/migrate` CLI (goose up/down)
- `internal/agent/store.go` — agent queries (insert, get, list, update, delete)
- `internal/wallet/store.go` — wallet queries
- `internal/payment/store.go` — payment config queries

**Modified files:**
- `go.mod` — promote indirect deps to direct where needed
- `cmd/api/main.go` — init Store, inject into routers, add auth middleware
- `internal/agent/handler.go` — wire store, replace TODO stubs
- `internal/wallet/handler.go` — wire store, replace TODO stubs
- `internal/payment/handler.go` — wire store, replace TODO stubs

---

## Task 1: Store package — DB connection

**Files:**
- Create: `internal/store/db.go`
- Create: `internal/store/store.go`

- [ ] **Step 1: Create `internal/store/db.go`**

```go
package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

func newPool(ctx context.Context, dsn string) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("parse db dsn: %w", err)
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("open db pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		return nil, fmt.Errorf("ping db: %w", err)
	}
	return pool, nil
}
```

- [ ] **Step 2: Create `internal/store/store.go`**

```go
package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

type Store struct {
	DB    *pgxpool.Pool
	Redis *redis.Client
}

func New(ctx context.Context, dbDSN, redisURL string) (*Store, error) {
	pool, err := newPool(ctx, dbDSN)
	if err != nil {
		return nil, fmt.Errorf("store db: %w", err)
	}
	rdb, err := newRedis(ctx, redisURL)
	if err != nil {
		pool.Close()
		return nil, fmt.Errorf("store redis: %w", err)
	}
	return &Store{DB: pool, Redis: rdb}, nil
}

func (s *Store) Close() {
	s.DB.Close()
	s.Redis.Close()
}
```

- [ ] **Step 3: Verify it compiles**

```bash
cd apps/api && go build ./internal/store/...
```
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add apps/api/internal/store/
git commit -m "feat(api): store package — pgx pool + redis client"
```

---

## Task 2: Store package — Redis connection

**Files:**
- Create: `internal/store/redis.go`

- [ ] **Step 1: Create `internal/store/redis.go`**

```go
package store

import (
	"context"
	"fmt"

	"github.com/redis/go-redis/v9"
)

func newRedis(ctx context.Context, url string) (*redis.Client, error) {
	opts, err := redis.ParseURL(url)
	if err != nil {
		return nil, fmt.Errorf("parse redis url: %w", err)
	}
	rdb := redis.NewClient(opts)
	if err := rdb.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("ping redis: %w", err)
	}
	return rdb, nil
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd apps/api && go build ./internal/store/...
```
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add apps/api/internal/store/redis.go
git commit -m "feat(api): store — redis client init"
```

---

## Task 3: Auth middleware

**Files:**
- Create: `internal/middleware/auth.go`

Better-auth issues HS256 JWTs signed with `BETTER_AUTH_SECRET`. The middleware validates the signature, checks expiry, and injects `userID` + `orgID` (from the `sub` and `orgId` claims) into the request context.

- [ ] **Step 1: Create `internal/middleware/auth.go`**

```go
package middleware

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/golang-jwt/jwt/v5"
)

type contextKey string

const (
	ctxUserID contextKey = "userID"
	ctxOrgID  contextKey = "orgID"
)

type claims struct {
	OrgID string `json:"orgId"`
	jwt.RegisteredClaims
}

// Auth returns a middleware that validates a Bearer JWT signed with secret.
func Auth(secret string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			raw := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
			if raw == "" {
				writeUnauth(w, "missing token")
				return
			}

			var c claims
			_, err := jwt.ParseWithClaims(raw, &c, func(t *jwt.Token) (any, error) {
				if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
					return nil, jwt.ErrSignatureInvalid
				}
				return []byte(secret), nil
			})
			if err != nil {
				writeUnauth(w, "invalid token")
				return
			}

			ctx := context.WithValue(r.Context(), ctxUserID, c.Subject)
			ctx = context.WithValue(ctx, ctxOrgID, c.OrgID)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// UserID extracts the authenticated user ID from ctx. Returns "" if not set.
func UserID(ctx context.Context) string {
	v, _ := ctx.Value(ctxUserID).(string)
	return v
}

// OrgID extracts the authenticated org ID from ctx. Returns "" if not set.
func OrgID(ctx context.Context) string {
	v, _ := ctx.Value(ctxOrgID).(string)
	return v
}

func writeUnauth(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd apps/api && go build ./internal/middleware/...
```
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add apps/api/internal/middleware/auth.go
git commit -m "feat(api): JWT auth middleware"
```

---

## Task 4: Request validation helper

**Files:**
- Create: `internal/middleware/validate.go`

- [ ] **Step 1: Create `internal/middleware/validate.go`**

```go
package middleware

import (
	"encoding/json"
	"net/http"

	"github.com/go-playground/validator/v10"
)

var validate = validator.New()

// Decode decodes JSON from r.Body into dst, validates struct tags, and writes
// a 400 response on failure. Returns false if the caller should abort.
func Decode(w http.ResponseWriter, r *http.Request, dst any) bool {
	if err := json.NewDecoder(r.Body).Decode(dst); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "invalid json"})
		return false
	}
	if err := validate.Struct(dst); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return false
	}
	return true
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd apps/api && go build ./internal/middleware/...
```
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add apps/api/internal/middleware/validate.go
git commit -m "feat(api): request decode+validate helper"
```

---

## Task 5: Migrations — users and orgs

**Files:**
- Create: `migrations/00001_users.sql`
- Create: `migrations/00002_orgs.sql`
- Create: `cmd/migrate/main.go`

- [ ] **Step 1: Create `migrations/00001_users.sql`**

```sql
-- +goose Up
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
```

- [ ] **Step 2: Create `migrations/00002_orgs.sql`**

```sql
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
    role       TEXT        NOT NULL DEFAULT 'member', -- 'owner' | 'admin' | 'member'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);

CREATE INDEX org_members_user_idx ON org_members (user_id);

-- +goose Down
DROP TABLE org_members;
DROP TABLE orgs;
```

- [ ] **Step 3: Create `cmd/migrate/main.go`**

```go
package main

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"os"

	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/joho/godotenv"
	"github.com/pressly/goose/v3"
)

func main() {
	_ = godotenv.Load()

	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		slog.Error("DATABASE_URL not set")
		os.Exit(1)
	}

	db, err := sql.Open("pgx", dsn)
	if err != nil {
		slog.Error("open db", "err", err)
		os.Exit(1)
	}
	defer db.Close()

	if err := db.PingContext(context.Background()); err != nil {
		slog.Error("ping db", "err", err)
		os.Exit(1)
	}

	goose.SetBaseFS(nil)

	cmd := "up"
	if len(os.Args) > 1 {
		cmd = os.Args[1]
	}

	if err := goose.RunContext(context.Background(), cmd, db, "migrations"); err != nil {
		fmt.Fprintf(os.Stderr, "goose %s: %v\n", cmd, err)
		os.Exit(1)
	}
}
```

- [ ] **Step 4: Verify it compiles**

```bash
cd apps/api && go build ./cmd/migrate/...
```
Expected: no output, exit 0.

- [ ] **Step 5: Commit**

```bash
git add apps/api/migrations/ apps/api/cmd/migrate/
git commit -m "feat(api): migrations 001-002 users+orgs, goose migrate cmd"
```

---

## Task 6: Migrations — agents, wallets, payment_configs, sessions

**Files:**
- Create: `migrations/00003_agents.sql`
- Create: `migrations/00004_wallets.sql`
- Create: `migrations/00005_payment_configs.sql`
- Create: `migrations/00006_sessions.sql`

- [ ] **Step 1: Create `migrations/00003_agents.sql`**

```sql
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
```

- [ ] **Step 2: Create `migrations/00004_wallets.sql`**

```sql
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

-- add FK from agents to wallets now that wallets table exists
ALTER TABLE agents
    ADD CONSTRAINT agents_wallet_fk
    FOREIGN KEY (wallet_id) REFERENCES wallets(id) ON DELETE SET NULL;

-- +goose Down
ALTER TABLE agents DROP CONSTRAINT agents_wallet_fk;
DROP TABLE wallets;
```

- [ ] **Step 3: Create `migrations/00005_payment_configs.sql`**

```sql
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
```

- [ ] **Step 4: Create `migrations/00006_sessions.sql`**

```sql
-- +goose Up
CREATE TABLE sessions (
    id             TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    agent_id       TEXT        NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    status         TEXT        NOT NULL DEFAULT 'active', -- 'active'|'completed'|'abandoned'
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

CREATE INDEX sessions_agent_idx     ON sessions       (agent_id);
CREATE INDEX session_events_sess_idx ON session_events (session_id);

-- +goose Down
DROP TABLE session_events;
DROP TABLE sessions;
```

- [ ] **Step 5: Verify migrations apply cleanly (requires infra up)**

```bash
# Start infra first if not running:
# bun run docker:up
cd apps/api && DATABASE_URL="postgres://ryo:ryo-app-dev@localhost:5433/ryo?sslmode=disable" go run ./cmd/migrate up
```
Expected: goose prints `OK   00001_users.sql` through `OK   00006_sessions.sql`.

- [ ] **Step 6: Commit**

```bash
git add apps/api/migrations/
git commit -m "feat(api): migrations 003-006 agents, wallets, payment_configs, sessions"
```

---

## Task 7: Agent domain — store queries

**Files:**
- Create: `internal/agent/store.go`

- [ ] **Step 1: Create `internal/agent/store.go`**

```go
package agent

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type agentStore struct {
	db *pgxpool.Pool
}

func newStore(db *pgxpool.Pool) *agentStore {
	return &agentStore{db: db}
}

func (s *agentStore) insert(ctx context.Context, a Agent) (Agent, error) {
	row := s.db.QueryRow(ctx, `
		INSERT INTO agents (id, org_id, name, business_type, system_prompt, tools, voice_enabled, embed_token, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9)
		RETURNING id, org_id, name, business_type, system_prompt, tools, voice_enabled, wallet_id, embed_token, created_at`,
		a.ID, a.OrgID, a.Name, a.BusinessType, a.SystemPrompt, a.Tools, a.VoiceEnabled, a.EmbedToken, time.Now().UTC(),
	)
	return scanAgent(row)
}

func (s *agentStore) get(ctx context.Context, id, orgID string) (Agent, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, org_id, name, business_type, system_prompt, tools, voice_enabled, wallet_id, embed_token, created_at
		FROM agents WHERE id = $1 AND org_id = $2`, id, orgID)
	return scanAgent(row)
}

func (s *agentStore) list(ctx context.Context, orgID string) ([]Agent, error) {
	rows, err := s.db.Query(ctx, `
		SELECT id, org_id, name, business_type, system_prompt, tools, voice_enabled, wallet_id, embed_token, created_at
		FROM agents WHERE org_id = $1 ORDER BY created_at DESC`, orgID)
	if err != nil {
		return nil, fmt.Errorf("list agents: %w", err)
	}
	defer rows.Close()

	var agents []Agent
	for rows.Next() {
		a, err := scanAgent(rows)
		if err != nil {
			return nil, err
		}
		agents = append(agents, a)
	}
	return agents, rows.Err()
}

func (s *agentStore) update(ctx context.Context, id, orgID string, req UpdateAgentRequest) (Agent, error) {
	row := s.db.QueryRow(ctx, `
		UPDATE agents SET
			name          = COALESCE(NULLIF($3, ''), name),
			system_prompt = COALESCE(NULLIF($4, ''), system_prompt),
			voice_enabled = $5,
			updated_at    = now()
		WHERE id = $1 AND org_id = $2
		RETURNING id, org_id, name, business_type, system_prompt, tools, voice_enabled, wallet_id, embed_token, created_at`,
		id, orgID, req.Name, req.SystemPrompt, req.VoiceEnabled,
	)
	return scanAgent(row)
}

func (s *agentStore) delete(ctx context.Context, id, orgID string) error {
	_, err := s.db.Exec(ctx, `DELETE FROM agents WHERE id = $1 AND org_id = $2`, id, orgID)
	return err
}

type scanner interface {
	Scan(dest ...any) error
}

func scanAgent(row scanner) (Agent, error) {
	var a Agent
	var walletID *string
	err := row.Scan(&a.ID, &a.OrgID, &a.Name, &a.BusinessType, &a.SystemPrompt, &a.Tools, &a.VoiceEnabled, &walletID, &a.EmbedToken, &a.CreatedAt)
	if err != nil {
		if err == pgx.ErrNoRows {
			return Agent{}, fmt.Errorf("not found")
		}
		return Agent{}, fmt.Errorf("scan agent: %w", err)
	}
	if walletID != nil {
		a.WalletID = *walletID
	}
	return a, nil
}
```

- [ ] **Step 2: Add `OrgID` and `UpdateAgentRequest` to `internal/agent/handler.go`**

The existing `Agent` struct needs an `OrgID` field, and we need `UpdateAgentRequest`. Replace the struct definitions at the top of `internal/agent/handler.go`:

```go
// Agent represents a configured agent instance.
type Agent struct {
	ID           string       `json:"id"`
	OrgID        string       `json:"org_id"`
	Name         string       `json:"name"`
	BusinessType BusinessType `json:"business_type"`
	SystemPrompt string       `json:"system_prompt"`
	Tools        []string     `json:"tools"`
	VoiceEnabled bool         `json:"voice_enabled"`
	WalletID     string       `json:"wallet_id,omitempty"`
	EmbedToken   string       `json:"embed_token"`
	CreatedAt    time.Time    `json:"created_at"`
}

// UpdateAgentRequest is the PATCH payload.
type UpdateAgentRequest struct {
	Name         string `json:"name"`
	SystemPrompt string `json:"system_prompt"`
	VoiceEnabled bool   `json:"voice_enabled"`
}
```

- [ ] **Step 3: Verify it compiles**

```bash
cd apps/api && go build ./internal/agent/...
```
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add apps/api/internal/agent/
git commit -m "feat(api): agent store queries"
```

---

## Task 8: Wire store into agent handler

**Files:**
- Modify: `internal/agent/handler.go`

- [ ] **Step 1: Replace `internal/agent/handler.go` with the wired version**

```go
package agent

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/apps/api/internal/middleware"
)

// Agent represents a configured agent instance.
type Agent struct {
	ID           string       `json:"id"`
	OrgID        string       `json:"org_id"`
	Name         string       `json:"name"`
	BusinessType BusinessType `json:"business_type"`
	SystemPrompt string       `json:"system_prompt"`
	Tools        []string     `json:"tools"`
	VoiceEnabled bool         `json:"voice_enabled"`
	WalletID     string       `json:"wallet_id,omitempty"`
	EmbedToken   string       `json:"embed_token"`
	CreatedAt    time.Time    `json:"created_at"`
}

// BusinessType shapes the agent's defaults.
type BusinessType string

const (
	BusinessTypeCafe       BusinessType = "cafe"
	BusinessTypeRestaurant BusinessType = "restaurant"
	BusinessTypeRetail     BusinessType = "retail"
	BusinessTypeService    BusinessType = "service"
	BusinessTypeCustom     BusinessType = "custom"
)

// CreateAgentRequest is the Studio wizard payload.
type CreateAgentRequest struct {
	Name         string       `json:"name"         validate:"required"`
	BusinessType BusinessType `json:"business_type" validate:"required"`
	SystemPrompt string       `json:"system_prompt"`
	Tools        []string     `json:"tools"`
	VoiceEnabled bool         `json:"voice_enabled"`
}

// UpdateAgentRequest is the PATCH payload.
type UpdateAgentRequest struct {
	Name         string `json:"name"`
	SystemPrompt string `json:"system_prompt"`
	VoiceEnabled bool   `json:"voice_enabled"`
}

type handler struct {
	store *agentStore
}

func Router(db *pgxpool.Pool) http.Handler {
	h := &handler{store: newStore(db)}
	r := chi.NewRouter()
	r.Post("/", h.createAgent)
	r.Get("/", h.listAgents)
	r.Get("/{id}", h.getAgent)
	r.Patch("/{id}", h.updateAgent)
	r.Delete("/{id}", h.deleteAgent)
	r.Get("/{id}/embed", h.getEmbedSnippet)
	return r
}

func (h *handler) createAgent(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	var req CreateAgentRequest
	if !middleware.Decode(w, r, &req) {
		return
	}
	if req.SystemPrompt == "" {
		req.SystemPrompt = defaultPrompt(req.BusinessType)
	}
	if len(req.Tools) == 0 {
		req.Tools = defaultTools(req.BusinessType)
	}
	a := Agent{
		ID:           uuid.New().String(),
		OrgID:        orgID,
		Name:         req.Name,
		BusinessType: req.BusinessType,
		SystemPrompt: req.SystemPrompt,
		Tools:        req.Tools,
		VoiceEnabled: req.VoiceEnabled,
		EmbedToken:   uuid.New().String(),
	}
	created, err := h.store.insert(r.Context(), a)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, created)
}

func (h *handler) listAgents(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	agents, err := h.store.list(r.Context(), orgID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if agents == nil {
		agents = []Agent{}
	}
	writeJSON(w, http.StatusOK, agents)
}

func (h *handler) getAgent(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	orgID := middleware.OrgID(r.Context())
	a, err := h.store.get(r.Context(), id, orgID)
	if err != nil {
		if errors.Is(err, errNotFound) || err.Error() == "not found" {
			writeError(w, http.StatusNotFound, "not found")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, a)
}

func (h *handler) updateAgent(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	orgID := middleware.OrgID(r.Context())
	var req UpdateAgentRequest
	if !middleware.Decode(w, r, &req) {
		return
	}
	updated, err := h.store.update(r.Context(), id, orgID, req)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, updated)
}

func (h *handler) deleteAgent(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	orgID := middleware.OrgID(r.Context())
	if err := h.store.delete(r.Context(), id, orgID); err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *handler) getEmbedSnippet(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	orgID := middleware.OrgID(r.Context())
	a, err := h.store.get(r.Context(), id, orgID)
	if err != nil {
		writeError(w, http.StatusNotFound, "not found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{
		"snippet": `<script src="https://cdn.ryo.dev/embed.js" data-agent="` + a.EmbedToken + `" async></script>`,
	})
}

var errNotFound = errors.New("not found")

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func defaultPrompt(bt BusinessType) string {
	switch bt {
	case BusinessTypeCafe, BusinessTypeRestaurant:
		return "You are a friendly ordering assistant. Help customers browse the menu, take their order accurately, confirm customisations, and process payment."
	case BusinessTypeRetail:
		return "You are a helpful shop assistant. Help customers find products, answer questions, and complete checkout."
	case BusinessTypeService:
		return "You are a helpful booking assistant. Help customers schedule appointments and process payment."
	default:
		return "You are a helpful business assistant."
	}
}

func defaultTools(bt BusinessType) []string {
	switch bt {
	case BusinessTypeCafe, BusinessTypeRestaurant:
		return []string{"get_menu", "add_to_order", "confirm_order", "request_payment", "send_receipt"}
	case BusinessTypeRetail:
		return []string{"search_products", "add_to_cart", "request_payment", "send_receipt"}
	case BusinessTypeService:
		return []string{"get_availability", "book_appointment", "request_payment", "send_confirmation"}
	default:
		return []string{"request_payment"}
	}
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd apps/api && go build ./internal/agent/...
```
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add apps/api/internal/agent/
git commit -m "feat(api): wire agent handler to store"
```

---

## Task 9: Wallet and payment store + handlers

**Files:**
- Create: `internal/wallet/store.go`
- Modify: `internal/wallet/handler.go`
- Create: `internal/payment/store.go`
- Modify: `internal/payment/handler.go`

- [ ] **Step 1: Create `internal/wallet/store.go`**

```go
package wallet

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type walletStore struct {
	db *pgxpool.Pool
}

func newStore(db *pgxpool.Pool) *walletStore {
	return &walletStore{db: db}
}

func (s *walletStore) insert(ctx context.Context, w Wallet) (Wallet, error) {
	row := s.db.QueryRow(ctx, `
		INSERT INTO wallets (id, org_id, provider, external_id, status, currency, kyb_required, kyb_portal_url, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)
		RETURNING id, org_id, provider, external_id, status, balance_cents, currency, kyb_required, kyb_portal_url, created_at`,
		w.ID, w.OrgID, w.Provider, nilIfEmpty(w.ExternalID), w.Status, w.Currency, w.KYBRequired, nilIfEmpty(w.KYBPortalURL), time.Now().UTC(),
	)
	return scanWallet(row)
}

func (s *walletStore) get(ctx context.Context, id, orgID string) (Wallet, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, org_id, provider, external_id, status, balance_cents, currency, kyb_required, kyb_portal_url, created_at
		FROM wallets WHERE id = $1 AND org_id = $2`, id, orgID)
	return scanWallet(row)
}

func (s *walletStore) getByOrg(ctx context.Context, orgID string) (Wallet, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, org_id, provider, external_id, status, balance_cents, currency, kyb_required, kyb_portal_url, created_at
		FROM wallets WHERE org_id = $1 ORDER BY created_at DESC LIMIT 1`, orgID)
	return scanWallet(row)
}

type scanner interface {
	Scan(dest ...any) error
}

func scanWallet(row scanner) (Wallet, error) {
	var w Wallet
	var externalID, kybPortalURL *string
	err := row.Scan(&w.ID, &w.OrgID, &w.Provider, &externalID, &w.Status, &w.BalanceCents, &w.Currency, &w.KYBRequired, &kybPortalURL, &w.CreatedAt)
	if err != nil {
		if err == pgx.ErrNoRows {
			return Wallet{}, fmt.Errorf("not found")
		}
		return Wallet{}, fmt.Errorf("scan wallet: %w", err)
	}
	if externalID != nil {
		w.ExternalID = *externalID
	}
	if kybPortalURL != nil {
		w.KYBPortalURL = *kybPortalURL
	}
	return w, nil
}

func nilIfEmpty(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
```

- [ ] **Step 2: Replace `internal/wallet/handler.go` with the wired version**

```go
package wallet

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/apps/api/internal/middleware"
)

type WalletStatus string

const (
	WalletStatusPending    WalletStatus = "pending"
	WalletStatusVerifying  WalletStatus = "verifying"
	WalletStatusActive     WalletStatus = "active"
	WalletStatusRestricted WalletStatus = "restricted"
)

type Wallet struct {
	ID           string       `json:"id"`
	OrgID        string       `json:"org_id"`
	Provider     string       `json:"provider"`
	ExternalID   string       `json:"external_id,omitempty"`
	Status       WalletStatus `json:"status"`
	BalanceCents int64        `json:"balance_cents"`
	Currency     string       `json:"currency"`
	KYBRequired  bool         `json:"kyb_required"`
	KYBPortalURL string       `json:"kyb_portal_url,omitempty"`
	CreatedAt    time.Time    `json:"created_at"`
}

type CreateWalletRequest struct {
	Provider      string `json:"provider"`
	Currency      string `json:"currency"`
	AutoConfigure bool   `json:"auto_configure"`
	ExternalID    string `json:"external_id"`
}

type handler struct {
	store *walletStore
}

func Router(db *pgxpool.Pool) http.Handler {
	h := &handler{store: newStore(db)}
	r := chi.NewRouter()
	r.Post("/", h.createWallet)
	r.Get("/", h.getWallet)
	r.Get("/balance", h.getBalance)
	r.Get("/transactions", h.listTransactions)
	return r
}

func (h *handler) createWallet(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	var req CreateWalletRequest
	if !middleware.Decode(w, r, &req) {
		return
	}
	if req.Provider == "" {
		req.Provider = "natural"
	}
	if req.Currency == "" {
		req.Currency = "usd"
	}
	wl := Wallet{
		ID:       uuid.New().String(),
		OrgID:    orgID,
		Provider: req.Provider,
		Status:   WalletStatusPending,
		Currency: req.Currency,
	}
	if req.AutoConfigure {
		wl.Status = WalletStatusVerifying
		wl.KYBRequired = true
		wl.KYBPortalURL = "https://verify.natural.co/placeholder"
	} else if req.ExternalID != "" {
		wl.ExternalID = req.ExternalID
		wl.Status = WalletStatusActive
	}
	created, err := h.store.insert(r.Context(), wl)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, created)
}

func (h *handler) getWallet(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	wl, err := h.store.getByOrg(r.Context(), orgID)
	if err != nil {
		if errors.Is(err, errNotFound) || err.Error() == "not found" {
			writeError(w, http.StatusNotFound, "no wallet found")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, wl)
}

func (h *handler) getBalance(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	wl, err := h.store.getByOrg(r.Context(), orgID)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"balance_cents": 0, "currency": "usd"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"balance_cents": wl.BalanceCents, "currency": wl.Currency})
}

func (h *handler) listTransactions(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, []any{})
}

var errNotFound = errors.New("not found")

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
```

- [ ] **Step 3: Create `internal/payment/store.go`**

```go
package payment

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type paymentStore struct {
	db *pgxpool.Pool
}

func newStore(db *pgxpool.Pool) *paymentStore {
	return &paymentStore{db: db}
}

func (s *paymentStore) insert(ctx context.Context, cfg PaymentConfig) (PaymentConfig, error) {
	row := s.db.QueryRow(ctx, `
		INSERT INTO payment_configs
			(id, agent_id, provider, collection_method, require_confirmation, max_auto_charge_amount, currency, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)
		RETURNING id, agent_id, provider, collection_method, require_confirmation, max_auto_charge_amount, currency, created_at`,
		cfg.ID, cfg.AgentID, cfg.Provider, cfg.CollectionMethod, cfg.RequireConfirmation, cfg.MaxAutoChargeAmount, cfg.Currency, time.Now().UTC(),
	)
	return scanConfig(row)
}

func (s *paymentStore) getByAgent(ctx context.Context, agentID string) (PaymentConfig, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, agent_id, provider, collection_method, require_confirmation, max_auto_charge_amount, currency, created_at
		FROM payment_configs WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 1`, agentID)
	return scanConfig(row)
}

type scanner interface {
	Scan(dest ...any) error
}

func scanConfig(row scanner) (PaymentConfig, error) {
	var c PaymentConfig
	err := row.Scan(&c.ID, &c.AgentID, &c.Provider, &c.CollectionMethod, &c.RequireConfirmation, &c.MaxAutoChargeAmount, &c.Currency, &c.CreatedAt)
	if err != nil {
		if err == pgx.ErrNoRows {
			return PaymentConfig{}, fmt.Errorf("not found")
		}
		return PaymentConfig{}, fmt.Errorf("scan payment config: %w", err)
	}
	return c, nil
}
```

- [ ] **Step 4: Replace `internal/payment/handler.go` with the wired version**

```go
package payment

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/apps/api/internal/middleware"
)

type Provider string

const (
	ProviderStripe  Provider = "stripe"
	ProviderNatural Provider = "natural"
	ProviderSquare  Provider = "square"
)

type CollectionMethod string

const (
	CollectionPhoneHandoff CollectionMethod = "phone_handoff"
	CollectionOneTimeLink  CollectionMethod = "one_time_link"
	CollectionWallet       CollectionMethod = "wallet"
	CollectionCardOnFile   CollectionMethod = "card_on_file"
)

type PaymentConfig struct {
	ID                  string           `json:"id"`
	AgentID             string           `json:"agent_id"`
	Provider            Provider         `json:"provider"`
	CollectionMethod    CollectionMethod `json:"collection_method"`
	ProviderAccountID   string           `json:"provider_account_id,omitempty"`
	RequireConfirmation bool             `json:"require_confirmation"`
	MaxAutoChargeAmount float64          `json:"max_auto_charge_amount"`
	Currency            string           `json:"currency"`
	CreatedAt           time.Time        `json:"created_at"`
}

type CreatePaymentConfigRequest struct {
	AgentID             string           `json:"agent_id"           validate:"required"`
	Provider            Provider         `json:"provider"           validate:"required"`
	CollectionMethod    CollectionMethod `json:"collection_method"  validate:"required"`
	APIKey              string           `json:"api_key"`
	RequireConfirmation bool             `json:"require_confirmation"`
	MaxAutoChargeAmount float64          `json:"max_auto_charge_amount"`
	Currency            string           `json:"currency"`
}

type handler struct {
	store *paymentStore
}

func Router(db *pgxpool.Pool) http.Handler {
	h := &handler{store: newStore(db)}
	r := chi.NewRouter()
	r.Post("/", h.createPaymentConfig)
	r.Get("/{agent_id}", h.getPaymentConfig)
	r.Patch("/{id}", h.updatePaymentConfig)
	r.Get("/providers", listProviders)
	return r
}

func (h *handler) createPaymentConfig(w http.ResponseWriter, r *http.Request) {
	var req CreatePaymentConfigRequest
	if !middleware.Decode(w, r, &req) {
		return
	}
	if req.Currency == "" {
		req.Currency = "usd"
	}
	cfg := PaymentConfig{
		ID:                  uuid.New().String(),
		AgentID:             req.AgentID,
		Provider:            req.Provider,
		CollectionMethod:    req.CollectionMethod,
		RequireConfirmation: req.RequireConfirmation,
		MaxAutoChargeAmount: req.MaxAutoChargeAmount,
		Currency:            req.Currency,
	}
	created, err := h.store.insert(r.Context(), cfg)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, created)
}

func (h *handler) getPaymentConfig(w http.ResponseWriter, r *http.Request) {
	agentID := chi.URLParam(r, "agent_id")
	cfg, err := h.store.getByAgent(r.Context(), agentID)
	if err != nil {
		if errors.Is(err, errNotFound) || err.Error() == "not found" {
			writeError(w, http.StatusNotFound, "not found")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, cfg)
}

func (h *handler) updatePaymentConfig(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusNoContent)
}

func listProviders(w http.ResponseWriter, r *http.Request) {
	providers := []map[string]any{
		{"id": "stripe", "name": "Stripe", "fields": []string{"api_key"}, "collection_methods": []string{"card_on_file", "one_time_link"}},
		{"id": "natural", "name": "Natural", "fields": []string{"api_key"}, "collection_methods": []string{"phone_handoff", "one_time_link", "wallet"}},
		{"id": "square", "name": "Square", "fields": []string{"api_key", "location_id"}, "collection_methods": []string{"card_on_file", "one_time_link"}},
	}
	writeJSON(w, http.StatusOK, providers)
}

var errNotFound = errors.New("not found")

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
```

- [ ] **Step 5: Verify all packages compile**

```bash
cd apps/api && go build ./...
```
Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
git add apps/api/internal/wallet/ apps/api/internal/payment/
git commit -m "feat(api): wire wallet and payment handlers to store"
```

---

## Task 10: Wire everything into main.go

**Files:**
- Modify: `cmd/api/main.go`

- [ ] **Step 1: Replace `cmd/api/main.go`**

```go
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	chimiddleware "github.com/go-chi/chi/v5/middleware"
	"github.com/go-chi/cors"
	"github.com/joho/godotenv"

	agenthandler "github.com/enkyuan/alloy/apps/api/internal/agent"
	"github.com/enkyuan/alloy/apps/api/internal/middleware"
	obshandler "github.com/enkyuan/alloy/apps/api/internal/observability"
	paymenthandler "github.com/enkyuan/alloy/apps/api/internal/payment"
	"github.com/enkyuan/alloy/apps/api/internal/store"
	wallethandler "github.com/enkyuan/alloy/apps/api/internal/wallet"
)

func main() {
	_ = godotenv.Load()

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	ctx := context.Background()

	s, err := store.New(ctx, mustEnv("DATABASE_URL"), mustEnv("REDIS_URL"))
	if err != nil {
		slog.Error("init store", "err", err)
		os.Exit(1)
	}
	defer s.Close()

	authSecret := mustEnv("BETTER_AUTH_SECRET")
	port := envOr("PORT", "8090")

	r := chi.NewRouter()
	r.Use(chimiddleware.RequestID)
	r.Use(chimiddleware.RealIP)
	r.Use(chimiddleware.Logger)
	r.Use(chimiddleware.Recoverer)
	r.Use(chimiddleware.Timeout(30 * time.Second))
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{envOr("STUDIO_ORIGIN", "http://localhost:5173")},
		AllowedMethods:   []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type"},
		AllowCredentials: true,
	}))

	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"ok"}`)
	})

	// Authenticated routes
	r.Group(func(r chi.Router) {
		r.Use(middleware.Auth(authSecret))
		r.Mount("/v1/agents", agenthandler.Router(s.DB))
		r.Mount("/v1/payments", paymenthandler.Router(s.DB))
		r.Mount("/v1/wallet", wallethandler.Router(s.DB))
		r.Mount("/v1/observability", obshandler.Router())
	})

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      r,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	go func() {
		slog.Info("api listening", "port", port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server error", "err", err)
			os.Exit(1)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	shutCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutCtx); err != nil {
		slog.Error("shutdown error", "err", err)
	}
	slog.Info("api stopped")
}

func mustEnv(key string) string {
	v := os.Getenv(key)
	if v == "" {
		slog.Error("required env var not set", "key", key)
		os.Exit(1)
	}
	return v
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
```

- [ ] **Step 2: Promote indirect deps to direct in go.mod**

```bash
cd apps/api && go mod tidy
```
Expected: go.mod updated, no errors.

- [ ] **Step 3: Verify the full binary compiles**

```bash
cd apps/api && go build ./cmd/api/...
```
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add apps/api/cmd/api/main.go apps/api/go.mod apps/api/go.sum
git commit -m "feat(api): wire store + auth middleware into main, all routes live"
```

---

## Task 11: Smoke test against live infra

- [ ] **Step 1: Start infra**

```bash
bun run docker:up
```
Expected: all containers healthy within ~30s.

- [ ] **Step 2: Run migrations**

```bash
cd apps/api && DATABASE_URL="postgres://ryo:ryo-app-dev@localhost:5433/ryo?sslmode=disable" go run ./cmd/migrate up
```
Expected: 6 migration files print `OK`.

- [ ] **Step 3: Start the API**

```bash
cd apps/api && DATABASE_URL="postgres://ryo:ryo-app-dev@localhost:5433/ryo?sslmode=disable" \
  REDIS_URL="redis://localhost:6380" \
  BETTER_AUTH_SECRET="dev-secret-change-in-prod" \
  go run ./cmd/api/main.go
```
Expected: `{"level":"INFO","msg":"api listening","port":"8090"}`

- [ ] **Step 4: Hit the health endpoint**

```bash
curl -s http://localhost:8090/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 5: Confirm auth middleware rejects unauthenticated requests**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8090/v1/agents
```
Expected: `401`

- [ ] **Step 6: Commit smoke test evidence (optional note in commit)**

```bash
git commit --allow-empty -m "chore(api): smoke test passed — store, migrations, auth middleware all live"
```
