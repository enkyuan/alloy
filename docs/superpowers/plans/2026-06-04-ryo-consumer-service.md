# ryo Consumer Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `apps/consumer` — a new Go service that handles consumer identity, Stripe payment method delegation, and the plain-language transaction/activity feed.

**Architecture:** Mirrors `apps/api` structure (chi router, pgx/v5, goose migrations, slog). Consumer JWTs use HS256 with a `role: consumer` claim, issued by this service only — separate from merchant JWTs. Stripe holds all payment data; the service stores only `stripe_customer_id`. `plain_label` strings are written at settlement time by the Stripe webhook callback in `apps/api`, which POSTs to an internal endpoint on this service.

**Tech Stack:** Go 1.25, chi v5, pgx/v5, goose migrations, `github.com/stripe/stripe-go/v82`, `golang-jwt/jwt/v5`, `golang.org/x/crypto/bcrypt`.

**Dependency:** Requires Plan 1 (ryo API extensions) to be deployed — the `apps/api` Stripe webhook handler writes consumer transaction rows by calling this service's internal endpoint.

---

## File Map

| file | action | responsibility |
|------|--------|---------------|
| `apps/consumer/go.mod` | create | module definition |
| `apps/consumer/cmd/migrate/main.go` | create | goose migration runner |
| `apps/consumer/cmd/consumer/main.go` | create | server entrypoint |
| `apps/consumer/migrations/00001_consumers.sql` | create | `consumers` table |
| `apps/consumer/migrations/00002_transactions.sql` | create | `consumer_transactions` table |
| `apps/consumer/internal/store/db.go` | create | pgxpool setup |
| `apps/consumer/internal/auth/handler.go` | create | signup, login, JWT issue |
| `apps/consumer/internal/auth/store.go` | create | consumer DB ops |
| `apps/consumer/internal/middleware/auth.go` | create | JWT validation middleware |
| `apps/consumer/internal/wallet/handler.go` | create | wallet status + SetupIntent |
| `apps/consumer/internal/transaction/handler.go` | create | transactions + activity feed |
| `apps/consumer/internal/transaction/store.go` | create | transaction DB ops |
| `apps/consumer/internal/internal/handler.go` | create | internal endpoint for writing transactions (called by `apps/api`) |

---

## Task 1: Scaffold the module

**Files:**
- Create: `apps/consumer/go.mod`
- Create: `apps/consumer/cmd/migrate/main.go`

- [ ] **Step 1: Create the module**

```bash
mkdir -p apps/consumer/cmd/migrate apps/consumer/cmd/consumer
cd apps/consumer && go mod init github.com/enkyuan/alloy/apps/consumer
go get github.com/go-chi/chi/v5@v5.2.0
go get github.com/go-chi/cors@v1.2.1
go get github.com/google/uuid@v1.6.0
go get github.com/jackc/pgx/v5@v5.9.2
go get github.com/joho/godotenv@v1.5.1
go get github.com/golang-jwt/jwt/v5@v5.3.1
go get github.com/pressly/goose/v3@v3.27.1
go get github.com/stripe/stripe-go/v82
go get golang.org/x/crypto
```

- [ ] **Step 2: Write the migration runner**

Create `apps/consumer/cmd/migrate/main.go`:

```go
package main

import (
	"context"
	"log/slog"
	"os"

	"github.com/jackc/pgx/v5/stdlib"
	"github.com/jackc/pgx/v5/pgxpool"
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
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		slog.Error("db connect", "err", err)
		os.Exit(1)
	}
	db := stdlib.OpenDBFromPool(pool)

	goose.SetBaseFS(nil)
	if err := goose.SetDialect("postgres"); err != nil {
		slog.Error("goose dialect", "err", err)
		os.Exit(1)
	}
	cmd := "up"
	if len(os.Args) > 1 {
		cmd = os.Args[1]
	}
	if err := goose.RunContext(context.Background(), cmd, db, "migrations"); err != nil {
		slog.Error("goose", "err", err)
		os.Exit(1)
	}
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/consumer/
git commit -m "feat(consumer): scaffold module + migration runner"
```

---

## Task 2: Migrations

**Files:**
- Create: `apps/consumer/migrations/00001_consumers.sql`
- Create: `apps/consumer/migrations/00002_transactions.sql`

- [ ] **Step 1: Write consumers migration**

Create `apps/consumer/migrations/00001_consumers.sql`:

```sql
-- +goose Up
CREATE TABLE consumers (
  id                 TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
  email              TEXT        NOT NULL UNIQUE,
  hashed_password    TEXT        NOT NULL,
  stripe_customer_id TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE consumers;
```

- [ ] **Step 2: Write transactions migration**

Create `apps/consumer/migrations/00002_transactions.sql`:

```sql
-- +goose Up
CREATE TABLE consumer_transactions (
  id           TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
  consumer_id  TEXT        NOT NULL REFERENCES consumers(id),
  session_id   TEXT        NOT NULL,
  amount_cents BIGINT      NOT NULL,
  currency     TEXT        NOT NULL DEFAULT 'usd',
  status       TEXT        NOT NULL CHECK (status IN ('pending','completed','failed')),
  plain_label  TEXT        NOT NULL,
  merchant_id  TEXT        NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX consumer_transactions_consumer_idx
  ON consumer_transactions (consumer_id, created_at DESC);

-- +goose Down
DROP TABLE consumer_transactions;
```

- [ ] **Step 3: Run migrations**

```bash
cd apps/consumer && go run ./cmd/migrate/main.go up
```

Expected: `OK   00001_consumers.sql`, `OK   00002_transactions.sql`

- [ ] **Step 4: Commit**

```bash
git add apps/consumer/migrations/
git commit -m "feat(consumer): consumers + consumer_transactions migrations"
```

---

## Task 3: DB store + auth store

**Files:**
- Create: `apps/consumer/internal/store/db.go`
- Create: `apps/consumer/internal/auth/store.go`
- Create: `apps/consumer/internal/auth/store_test.go`

- [ ] **Step 1: Write the failing test**

Create `apps/consumer/internal/auth/store_test.go`:

```go
package auth_test

import (
	"context"
	"os"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/apps/consumer/internal/auth"
)

func testDB(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set")
	}
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func TestCreateAndGetConsumer(t *testing.T) {
	db := testDB(t)
	s := auth.NewStore(db)

	c, err := s.Create(context.Background(), "test@example.com", "hashed")
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if c.Email != "test@example.com" {
		t.Errorf("email mismatch")
	}

	got, err := s.GetByEmail(context.Background(), "test@example.com")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.ID != c.ID {
		t.Errorf("id mismatch")
	}
	t.Cleanup(func() { db.Exec(context.Background(), `DELETE FROM consumers WHERE id=$1`, c.ID) })
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/consumer && go test ./internal/auth/... -v
```

Expected: `cannot find package`

- [ ] **Step 3: Write db.go**

Create `apps/consumer/internal/store/db.go`:

```go
package store

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

// New opens a pgxpool connection.
func New(ctx context.Context, dsn string) (*pgxpool.Pool, error) {
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return nil, fmt.Errorf("pgxpool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping: %w", err)
	}
	return pool, nil
}
```

- [ ] **Step 4: Write auth store**

Create `apps/consumer/internal/auth/store.go`:

```go
package auth

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Consumer is the identity record.
type Consumer struct {
	ID               string    `json:"id"`
	Email            string    `json:"email"`
	HashedPassword   string    `json:"-"`
	StripeCustomerID string    `json:"stripe_customer_id,omitempty"`
	CreatedAt        time.Time `json:"created_at"`
}

// Store handles consumer persistence.
type Store struct {
	db *pgxpool.Pool
}

// NewStore creates a Store backed by db.
func NewStore(db *pgxpool.Pool) *Store {
	return &Store{db: db}
}

// Create inserts a new consumer.
func (s *Store) Create(ctx context.Context, email, hashedPassword string) (Consumer, error) {
	row := s.db.QueryRow(ctx, `
		INSERT INTO consumers (id, email, hashed_password, created_at)
		VALUES (gen_random_uuid()::text, $1, $2, now())
		RETURNING id, email, hashed_password, stripe_customer_id, created_at`,
		email, hashedPassword)
	return scanConsumer(row)
}

// GetByEmail fetches a consumer by email.
func (s *Store) GetByEmail(ctx context.Context, email string) (Consumer, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, email, hashed_password, stripe_customer_id, created_at
		FROM consumers WHERE email = $1`, email)
	return scanConsumer(row)
}

// GetByID fetches a consumer by primary key.
func (s *Store) GetByID(ctx context.Context, id string) (Consumer, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, email, hashed_password, stripe_customer_id, created_at
		FROM consumers WHERE id = $1`, id)
	return scanConsumer(row)
}

// SetStripeCustomerID persists the Stripe customer ID after first setup.
func (s *Store) SetStripeCustomerID(ctx context.Context, id, stripeCustomerID string) error {
	_, err := s.db.Exec(ctx,
		`UPDATE consumers SET stripe_customer_id=$2 WHERE id=$1`, id, stripeCustomerID)
	return err
}

func scanConsumer(row interface {
	Scan(dest ...any) error
}) (Consumer, error) {
	var c Consumer
	var custID *string
	err := row.Scan(&c.ID, &c.Email, &c.HashedPassword, &custID, &c.CreatedAt)
	if err != nil {
		if err == pgx.ErrNoRows {
			return Consumer{}, fmt.Errorf("not found")
		}
		return Consumer{}, fmt.Errorf("scan consumer: %w", err)
	}
	if custID != nil {
		c.StripeCustomerID = *custID
	}
	return c, nil
}
```

- [ ] **Step 5: Run tests**

```bash
cd apps/consumer && go test ./internal/auth/... -v
```

Expected: PASS or SKIP.

- [ ] **Step 6: Commit**

```bash
git add apps/consumer/internal/
git commit -m "feat(consumer): db store + auth store"
```

---

## Task 4: JWT middleware

**Files:**
- Create: `apps/consumer/internal/middleware/auth.go`
- Create: `apps/consumer/internal/middleware/auth_test.go`

- [ ] **Step 1: Write the failing test**

Create `apps/consumer/internal/middleware/auth_test.go`:

```go
package middleware_test

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/enkyuan/alloy/apps/consumer/internal/middleware"
)

func makeToken(secret, consumerID, role string) string {
	claims := jwt.MapClaims{
		"sub":  consumerID,
		"role": role,
		"exp":  time.Now().Add(time.Hour).Unix(),
	}
	tok, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(secret))
	return tok
}

func TestAuth_ValidToken(t *testing.T) {
	secret := "testsecret"
	var gotID string
	handler := middleware.Auth(secret)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotID = middleware.ConsumerID(r.Context())
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken(secret, "consumer-1", "consumer"))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", rr.Code)
	}
	if gotID != "consumer-1" {
		t.Errorf("consumer id: got %q, want consumer-1", gotID)
	}
}

func TestAuth_MissingToken(t *testing.T) {
	handler := middleware.Auth("secret")(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusUnauthorized {
		t.Errorf("expected 401, got %d", rr.Code)
	}
}

func TestAuth_WrongRole(t *testing.T) {
	secret := "testsecret"
	handler := middleware.Auth(secret)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer "+makeToken(secret, "user-1", "merchant"))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	if rr.Code != http.StatusUnauthorized {
		t.Errorf("expected 401 for wrong role, got %d", rr.Code)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/consumer && go test ./internal/middleware/... -v
```

Expected: `cannot find package`

- [ ] **Step 3: Write the middleware**

Create `apps/consumer/internal/middleware/auth.go`:

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

const ctxConsumerID contextKey = "consumerID"

type claims struct {
	Role string `json:"role"`
	jwt.RegisteredClaims
}

// Auth validates a Bearer JWT with role=consumer.
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
			if c.Role != "consumer" {
				writeUnauth(w, "forbidden")
				return
			}
			ctx := context.WithValue(r.Context(), ctxConsumerID, c.Subject)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// ConsumerID extracts the consumer ID from ctx.
func ConsumerID(ctx context.Context) string {
	v, _ := ctx.Value(ctxConsumerID).(string)
	return v
}

func writeUnauth(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	json.NewEncoder(w).Encode(map[string]string{"error": msg}) //nolint:errcheck
}
```

- [ ] **Step 4: Run tests**

```bash
cd apps/consumer && go test ./internal/middleware/... -v
```

Expected: `TestAuth_ValidToken PASS`, `TestAuth_MissingToken PASS`, `TestAuth_WrongRole PASS`

- [ ] **Step 5: Commit**

```bash
git add apps/consumer/internal/middleware/
git commit -m "feat(consumer): JWT auth middleware with role=consumer check"
```

---

## Task 5: Auth handler (signup + login)

**Files:**
- Create: `apps/consumer/internal/auth/handler.go`

- [ ] **Step 1: Write the handler**

Create `apps/consumer/internal/auth/handler.go`:

```go
package auth

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
)

type handler struct {
	store     *Store
	jwtSecret string
}

// Router mounts auth routes (no JWT required).
func Router(db *pgxpool.Pool, jwtSecret string) http.Handler {
	h := &handler{store: NewStore(db), jwtSecret: jwtSecret}
	r := chi.NewRouter()
	r.Post("/signup", h.signup)
	r.Post("/login", h.login)
	return r
}

type signupRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type loginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

func (h *handler) signup(w http.ResponseWriter, r *http.Request) {
	var req signupRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid json")
		return
	}
	req.Email = strings.ToLower(strings.TrimSpace(req.Email))
	if req.Email == "" || req.Password == "" {
		writeErr(w, http.StatusBadRequest, "email and password required")
		return
	}
	hashed, err := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "hash error")
		return
	}
	consumer, err := h.store.Create(r.Context(), req.Email, string(hashed))
	if err != nil {
		if strings.Contains(err.Error(), "unique") {
			writeErr(w, http.StatusConflict, "email already registered")
			return
		}
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	token, err := h.issueToken(consumer.ID)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "token error")
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"token": token, "consumer": consumer})
}

func (h *handler) login(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid json")
		return
	}
	consumer, err := h.store.GetByEmail(r.Context(), strings.ToLower(strings.TrimSpace(req.Email)))
	if err != nil {
		writeErr(w, http.StatusUnauthorized, "invalid credentials")
		return
	}
	if err := bcrypt.CompareHashAndPassword([]byte(consumer.HashedPassword), []byte(req.Password)); err != nil {
		writeErr(w, http.StatusUnauthorized, "invalid credentials")
		return
	}
	token, err := h.issueToken(consumer.ID)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "token error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"token": token, "consumer": consumer})
}

func (h *handler) issueToken(consumerID string) (string, error) {
	claims := jwt.MapClaims{
		"sub":  consumerID,
		"role": "consumer",
		"exp":  time.Now().Add(24 * time.Hour * 30).Unix(),
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(h.jwtSecret))
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v) //nolint:errcheck
}

func writeErr(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
```

- [ ] **Step 2: Build**

```bash
cd apps/consumer && go build ./...
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/consumer/internal/auth/handler.go
git commit -m "feat(consumer): auth handler — signup + login"
```

---

## Task 6: Transaction store + handler

**Files:**
- Create: `apps/consumer/internal/transaction/store.go`
- Create: `apps/consumer/internal/transaction/handler.go`

- [ ] **Step 1: Write the transaction store**

Create `apps/consumer/internal/transaction/store.go`:

```go
package transaction

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Transaction is an entry in the consumer's payment ledger.
type Transaction struct {
	ID          string    `json:"id"`
	ConsumerID  string    `json:"consumer_id"`
	SessionID   string    `json:"session_id"`
	AmountCents int64     `json:"amount_cents"`
	Currency    string    `json:"currency"`
	Status      string    `json:"status"`
	PlainLabel  string    `json:"plain_label"`
	MerchantID  string    `json:"merchant_id"`
	CreatedAt   time.Time `json:"created_at"`
}

// Store handles transaction persistence.
type Store struct {
	db *pgxpool.Pool
}

// NewStore creates a Store backed by db.
func NewStore(db *pgxpool.Pool) *Store {
	return &Store{db: db}
}

// Insert appends a new transaction row (append-only).
func (s *Store) Insert(ctx context.Context, tx Transaction) (Transaction, error) {
	row := s.db.QueryRow(ctx, `
		INSERT INTO consumer_transactions
		  (id, consumer_id, session_id, amount_cents, currency, status, plain_label, merchant_id, created_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		RETURNING id, consumer_id, session_id, amount_cents, currency, status, plain_label, merchant_id, created_at`,
		tx.ID, tx.ConsumerID, tx.SessionID, tx.AmountCents, tx.Currency,
		tx.Status, tx.PlainLabel, tx.MerchantID, tx.CreatedAt,
	)
	return scanTx(row)
}

// List returns paginated transactions for a consumer, newest first.
func (s *Store) List(ctx context.Context, consumerID string, limit, offset int) ([]Transaction, error) {
	rows, err := s.db.Query(ctx, `
		SELECT id, consumer_id, session_id, amount_cents, currency, status, plain_label, merchant_id, created_at
		FROM consumer_transactions
		WHERE consumer_id = $1
		ORDER BY created_at DESC
		LIMIT $2 OFFSET $3`, consumerID, limit, offset)
	if err != nil {
		return nil, fmt.Errorf("list transactions: %w", err)
	}
	defer rows.Close()
	var out []Transaction
	for rows.Next() {
		tx, err := scanTx(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, tx)
	}
	return out, rows.Err()
}

func scanTx(row interface {
	Scan(dest ...any) error
}) (Transaction, error) {
	var tx Transaction
	err := row.Scan(&tx.ID, &tx.ConsumerID, &tx.SessionID, &tx.AmountCents,
		&tx.Currency, &tx.Status, &tx.PlainLabel, &tx.MerchantID, &tx.CreatedAt)
	if err != nil {
		return Transaction{}, fmt.Errorf("scan transaction: %w", err)
	}
	return tx, nil
}
```

- [ ] **Step 2: Write the transaction handler**

Create `apps/consumer/internal/transaction/handler.go`:

```go
package transaction

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/apps/consumer/internal/middleware"
)

type handler struct {
	store *Store
}

// Router mounts transaction + activity routes (requires JWT middleware already applied).
func Router(db *pgxpool.Pool) http.Handler {
	h := &handler{store: NewStore(db)}
	r := chi.NewRouter()
	r.Get("/", h.list)
	return r
}

// ActivityRouter mounts the plain-language activity feed.
func ActivityRouter(db *pgxpool.Pool) http.Handler {
	h := &handler{store: NewStore(db)}
	r := chi.NewRouter()
	r.Get("/", h.activity)
	return r
}

func (h *handler) list(w http.ResponseWriter, r *http.Request) {
	consumerID := middleware.ConsumerID(r.Context())
	limit := queryInt(r, "limit", 20)
	offset := queryInt(r, "offset", 0)
	txs, err := h.store.List(r.Context(), consumerID, limit, offset)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	if txs == nil {
		txs = []Transaction{}
	}
	writeJSON(w, http.StatusOK, txs)
}

func (h *handler) activity(w http.ResponseWriter, r *http.Request) {
	consumerID := middleware.ConsumerID(r.Context())
	limit := queryInt(r, "limit", 20)
	offset := queryInt(r, "offset", 0)
	txs, err := h.store.List(r.Context(), consumerID, limit, offset)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	// Activity feed is just the plain_label strings, oldest-first read
	type entry struct {
		ID         string `json:"id"`
		PlainLabel string `json:"label"`
		Status     string `json:"status"`
		CreatedAt  string `json:"created_at"`
	}
	out := make([]entry, 0, len(txs))
	for _, tx := range txs {
		out = append(out, entry{
			ID:         tx.ID,
			PlainLabel: tx.PlainLabel,
			Status:     tx.Status,
			CreatedAt:  tx.CreatedAt.Format("2006-01-02T15:04:05Z"),
		})
	}
	writeJSON(w, http.StatusOK, out)
}

func queryInt(r *http.Request, key string, def int) int {
	v := r.URL.Query().Get(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < 0 {
		return def
	}
	return n
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v) //nolint:errcheck
}

func writeErr(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
```

- [ ] **Step 3: Build**

```bash
cd apps/consumer && go build ./...
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/consumer/internal/transaction/
git commit -m "feat(consumer): transaction store + handler"
```

---

## Task 7: Wallet handler

**Files:**
- Create: `apps/consumer/internal/wallet/handler.go`

- [ ] **Step 1: Write the wallet handler**

Create `apps/consumer/internal/wallet/handler.go`:

```go
package wallet

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	stripe "github.com/stripe/stripe-go/v82"
	"github.com/stripe/stripe-go/v82/customer"
	"github.com/stripe/stripe-go/v82/setupintent"

	"github.com/enkyuan/alloy/apps/consumer/internal/auth"
	"github.com/enkyuan/alloy/apps/consumer/internal/middleware"
)

type handler struct {
	consumerStore *auth.Store
}

// Router mounts wallet routes.
func Router(db *pgxpool.Pool, stripeKey string) http.Handler {
	stripe.Key = stripeKey
	h := &handler{consumerStore: auth.NewStore(db)}
	r := chi.NewRouter()
	r.Get("/", h.status)
	r.Post("/setup", h.setup)
	return r
}

func (h *handler) status(w http.ResponseWriter, r *http.Request) {
	consumerID := middleware.ConsumerID(r.Context())
	c, err := h.consumerStore.GetByID(r.Context(), consumerID)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	if c.StripeCustomerID == "" {
		writeJSON(w, http.StatusOK, map[string]any{
			"stripe_customer_id": nil,
			"payment_methods":    []any{},
		})
		return
	}
	// List saved payment methods from Stripe
	params := &stripe.PaymentMethodListParams{
		Customer: stripe.String(c.StripeCustomerID),
		Type:     stripe.String("card"),
	}
	iter := stripe.PaymentMethodList(params)
	var methods []map[string]any
	for iter.Next() {
		pm := iter.PaymentMethod()
		methods = append(methods, map[string]any{
			"id":    pm.ID,
			"brand": pm.Card.Brand,
			"last4": pm.Card.Last4,
			"exp":   map[string]any{"month": pm.Card.ExpMonth, "year": pm.Card.ExpYear},
		})
	}
	if methods == nil {
		methods = []map[string]any{}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"stripe_customer_id": c.StripeCustomerID,
		"payment_methods":    methods,
	})
}

func (h *handler) setup(w http.ResponseWriter, r *http.Request) {
	consumerID := middleware.ConsumerID(r.Context())
	c, err := h.consumerStore.GetByID(r.Context(), consumerID)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	// Create Stripe customer if not yet created
	if c.StripeCustomerID == "" {
		cust, err := customer.New(&stripe.CustomerParams{Email: stripe.String(c.Email)})
		if err != nil {
			writeErr(w, http.StatusBadGateway, "stripe error: "+err.Error())
			return
		}
		if err := h.consumerStore.SetStripeCustomerID(r.Context(), consumerID, cust.ID); err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		c.StripeCustomerID = cust.ID
	}
	// Create SetupIntent
	si, err := setupintent.New(&stripe.SetupIntentParams{
		Customer: stripe.String(c.StripeCustomerID),
		PaymentMethodTypes: stripe.StringSlice([]string{"card"}),
	})
	if err != nil {
		writeErr(w, http.StatusBadGateway, "stripe error: "+err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"client_secret": si.ClientSecret})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v) //nolint:errcheck
}

func writeErr(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
```

- [ ] **Step 2: Build**

```bash
cd apps/consumer && go build ./...
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/consumer/internal/wallet/
git commit -m "feat(consumer): wallet handler — status + Stripe SetupIntent"
```

---

## Task 8: Internal endpoint (receives transaction writes from apps/api)

**Files:**
- Create: `apps/consumer/internal/internal/handler.go`

- [ ] **Step 1: Write the internal handler**

Create `apps/consumer/internal/internal/handler.go`:

```go
// Package internal exposes an endpoint called only by @ryo/api (not
// consumers). It is secured by a shared internal secret rather than a consumer JWT.
package internal

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/apps/consumer/internal/transaction"
)

type handler struct {
	store          *transaction.Store
	internalSecret string
}

// Router mounts the internal write endpoint.
func Router(db *pgxpool.Pool, internalSecret string) http.Handler {
	h := &handler{store: transaction.NewStore(db), internalSecret: internalSecret}
	r := chi.NewRouter()
	r.Use(h.requireSecret)
	r.Post("/transactions", h.writeTransaction)
	return r
}

type writeTransactionRequest struct {
	ConsumerStripeCustomerID string `json:"consumer_stripe_customer_id"`
	SessionID                string `json:"session_id"`
	AmountCents              int64  `json:"amount_cents"`
	Currency                 string `json:"currency"`
	Status                   string `json:"status"`
	MerchantName             string `json:"merchant_name"`
	MerchantID               string `json:"merchant_id"`
	ActionDescription        string `json:"action_description"`
}

func (h *handler) requireSecret(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Internal-Secret") != h.internalSecret {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (h *handler) writeTransaction(w http.ResponseWriter, r *http.Request) {
	var req writeTransactionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}

	// Build plain_label
	plainLabel := buildPlainLabel(req.MerchantName, req.ActionDescription, req.AmountCents, req.Currency, req.Status)

	tx := transaction.Transaction{
		ID:          uuid.New().String(),
		ConsumerID:  req.ConsumerStripeCustomerID, // resolved externally — see note below
		SessionID:   req.SessionID,
		AmountCents: req.AmountCents,
		Currency:    req.Currency,
		Status:      req.Status,
		PlainLabel:  plainLabel,
		MerchantID:  req.MerchantID,
		CreatedAt:   time.Now().UTC(),
	}
	// Note: ConsumerID here is set to the consumer's ryo ID, which the
	// caller (apps/api) must resolve from stripe_customer_id before calling.
	// The API looks up the consumer service's GET /internal/consumers?stripe_id=...
	// endpoint (add that lookup in apps/api's Stripe webhook handler).
	created, err := h.store.Insert(r.Context(), tx)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(created) //nolint:errcheck
}

func buildPlainLabel(merchantName, action string, amountCents int64, currency, status string) string {
	amount := float64(amountCents) / 100
	if status == "failed" {
		return "Payment to " + merchantName + " failed - no charge made"
	}
	if action != "" {
		return "Agent at " + merchantName + " " + action + " - $" + formatAmount(amount)
	}
	return "Payment to " + merchantName + " - $" + formatAmount(amount)
}

func formatAmount(amount float64) string {
	return fmt.Sprintf("%.2f", amount)
}
```

- [ ] **Step 2: Add missing fmt import**

The file uses `fmt.Sprintf` — add `"fmt"` to the import block in `apps/consumer/internal/internal/handler.go`.

- [ ] **Step 3: Build**

```bash
cd apps/consumer && go build ./...
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/consumer/internal/internal/
git commit -m "feat(consumer): internal transaction write endpoint"
```

---

## Task 9: Main entrypoint

**Files:**
- Create: `apps/consumer/cmd/consumer/main.go`
- Create: `apps/consumer/.env.example`

- [ ] **Step 1: Write main.go**

Create `apps/consumer/cmd/consumer/main.go`:

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

	authhandler "github.com/enkyuan/alloy/apps/consumer/internal/auth"
	internalhandler "github.com/enkyuan/alloy/apps/consumer/internal/internal"
	jwtmiddleware "github.com/enkyuan/alloy/apps/consumer/internal/middleware"
	"github.com/enkyuan/alloy/apps/consumer/internal/store"
	txhandler "github.com/enkyuan/alloy/apps/consumer/internal/transaction"
	wallethandler "github.com/enkyuan/alloy/apps/consumer/internal/wallet"
)

func main() {
	_ = godotenv.Load()

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	ctx := context.Background()

	db, err := store.New(ctx, mustEnv("DATABASE_URL"))
	if err != nil {
		slog.Error("init db", "err", err)
		os.Exit(1)
	}
	defer db.Close()

	jwtSecret := mustEnv("JWT_SECRET")
	stripeKey := mustEnv("STRIPE_SECRET_KEY")
	internalSecret := mustEnv("INTERNAL_SECRET")
	port := envOr("PORT", "8091")

	r := chi.NewRouter()
	r.Use(chimiddleware.RequestID)
	r.Use(chimiddleware.RealIP)
	r.Use(chimiddleware.Logger)
	r.Use(chimiddleware.Recoverer)
	r.Use(chimiddleware.Timeout(30 * time.Second))
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{envOr("APP_ORIGIN", "http://localhost:5173")},
		AllowedMethods:   []string{"GET", "POST", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type"},
		AllowCredentials: true,
	}))

	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"ok"}`)
	})

	// Public auth routes
	r.Mount("/v1/auth", authhandler.Router(db, jwtSecret))

	// Internal routes (service-to-service, no consumer JWT)
	r.Mount("/internal", internalhandler.Router(db, internalSecret))

	// Protected consumer routes
	r.Group(func(r chi.Router) {
		r.Use(jwtmiddleware.Auth(jwtSecret))
		r.Mount("/v1/wallet", wallethandler.Router(db, stripeKey))
		r.Mount("/v1/transactions", txhandler.Router(db))
		r.Mount("/v1/activity", txhandler.ActivityRouter(db))
	})

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      r,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	go func() {
		slog.Info("consumer service listening", "port", port)
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
	slog.Info("consumer service stopped")
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

- [ ] **Step 2: Write .env.example**

Create `apps/consumer/.env.example`:

```
DATABASE_URL=postgres://postgres:postgres@localhost:5432/ryo_consumer
JWT_SECRET=change-me
STRIPE_SECRET_KEY=sk_test_...
INTERNAL_SECRET=change-me-internal
PORT=8091
APP_ORIGIN=http://localhost:5173
```

- [ ] **Step 3: Build**

```bash
cd apps/consumer && go build ./...
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/consumer/cmd/ apps/consumer/.env.example
git commit -m "feat(consumer): service entrypoint — all routes wired"
```

---

## Task 10: Smoke test

- [ ] **Step 1: Start the consumer service**

```bash
cd apps/consumer && go run ./cmd/migrate/main.go up && go run ./cmd/consumer/main.go
```

Expected: `consumer service listening port=8091`

- [ ] **Step 2: Health check**

```bash
curl http://localhost:8091/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 3: Signup**

```bash
curl -X POST http://localhost:8091/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password123"}'
```

Expected: `201` with `token` and `consumer` fields.

- [ ] **Step 4: Get wallet (requires token from step 3)**

```bash
curl http://localhost:8091/v1/wallet \
  -H "Authorization: Bearer <token>"
```

Expected: `200` with `stripe_customer_id: null, payment_methods: []`

- [ ] **Step 5: Commit smoke test notes**

```bash
git commit --allow-empty -m "chore(consumer): smoke test passed — auth, wallet, activity routes"
```
