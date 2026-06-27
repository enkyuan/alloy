package session_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/ryo/api/internal/session"
)

// stripeKeyForTest is intentionally non-functional. The replay path in
// createSession returns BEFORE any Stripe call, so a fake key is enough to
// exercise it without making a network call.
const stripeKeyForTest = "sk_test_FAKE_FOR_REPLAY_PATH_ONLY"

// TestCreateSession_ReplayOnIdempotencyKey verifies the replay short-circuit:
// once a session exists for a given Idempotency-Key, a second POST with the
// same key returns the SAME session id without touching Stripe.
func TestCreateSession_ReplayOnIdempotencyKey(t *testing.T) {
	db := setupTestDBForIdempotency(t)
	ctx := context.Background()

	// Seed org + agent + a pre-existing session that already used "key-abc".
	orgID := "org-idem-" + t.Name()
	agentID := "agent-idem-" + t.Name()
	if _, err := db.Exec(ctx,
		`INSERT INTO orgs (id, name, slug, created_at) VALUES ($1,$1,$1,now()) ON CONFLICT DO NOTHING`,
		orgID); err != nil {
		t.Fatalf("seed org: %v", err)
	}
	if _, err := db.Exec(ctx, `
		INSERT INTO agents (id, org_id, name, business_type, system_prompt, tools, voice_enabled, embed_token, created_at, updated_at)
		VALUES ($1, $2, 'test', 'custom', '', '{}', false, $1, now(), now()) ON CONFLICT DO NOTHING`,
		agentID, orgID); err != nil {
		t.Fatalf("seed agent: %v", err)
	}
	t.Cleanup(func() {
		db.Exec(ctx, `DELETE FROM agents WHERE id=$1`, agentID)
		db.Exec(ctx, `DELETE FROM orgs WHERE id=$1`, orgID)
	})

	store := session.NewStore(db)
	existingID := "sess-idem-existing-" + t.Name()
	// Seed with empty StripePaymentIntentID so the replay path skips the
	// paymentintent.Get call entirely. The test's purpose is to verify the
	// short-circuit on Idempotency-Key match; the PaymentIntent re-fetch is
	// exercised by tests that have a real (or mocked) Stripe client.
	existing, err := store.Insert(ctx, session.Session{
		ID:                   existingID,
		AgentID:              agentID,
		Channel:              "chat",
		Status:               "pending",
		AmountCollectedCents: 500,
		Currency:             "usd",
		StartedAt:            time.Now().UTC(),
		IdempotencyKey:       "key-abc-" + t.Name(),
	})
	if err != nil {
		t.Fatalf("seed session: %v", err)
	}
	t.Cleanup(func() { db.Exec(ctx, `DELETE FROM sessions WHERE id=$1`, existing.ID) })

	router := session.Router(db, stripeKeyForTest)
	body := `{"agent_id":"` + agentID + `","amount_cents":500,"currency":"usd"}`
	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", "key-abc-"+t.Name())
	w := httptest.NewRecorder()

	router.ServeHTTP(w, req)

	if w.Code != http.StatusCreated {
		t.Fatalf("status: got %d, want 201; body=%s", w.Code, w.Body.String())
	}

	var resp map[string]any
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	sess, _ := resp["session"].(map[string]any)
	if sess == nil || sess["id"] != existingID {
		t.Errorf("replay did not return original session: got %v, want id=%q", sess, existingID)
	}
	// No PI ID was seeded, so client_secret must be absent (we didn't call
	// paymentintent.Get, which is the whole point of the no-Stripe assertion).
	if _, ok := resp["client_secret"]; ok {
		t.Errorf("client_secret unexpectedly present on replay with no PI ID: %v", resp["client_secret"])
	}

	// Confirm only ONE row exists for this key (no duplicate insert).
	var n int
	if err := db.QueryRow(ctx,
		`SELECT count(*) FROM sessions WHERE idempotency_key=$1`,
		"key-abc-"+t.Name()).Scan(&n); err != nil {
		t.Fatalf("count: %v", err)
	}
	if n != 1 {
		t.Errorf("idempotent insert leaked a row: count=%d, want 1", n)
	}
}

// TestStore_GetByIdempotencyKey covers the store-level primitive directly so
// we still have signal when TEST_DATABASE_URL is unavailable for the HTTP test.
func TestStore_GetByIdempotencyKey(t *testing.T) {
	db := setupTestDBForIdempotency(t)
	ctx := context.Background()
	store := session.NewStore(db)

	orgID := "org-key-" + t.Name()
	agentID := "agent-key-" + t.Name()
	if _, err := db.Exec(ctx,
		`INSERT INTO orgs (id, name, slug, created_at) VALUES ($1,$1,$1,now()) ON CONFLICT DO NOTHING`,
		orgID); err != nil {
		t.Fatalf("seed org: %v", err)
	}
	if _, err := db.Exec(ctx, `
		INSERT INTO agents (id, org_id, name, business_type, system_prompt, tools, voice_enabled, embed_token, created_at, updated_at)
		VALUES ($1, $2, 'test', 'custom', '', '{}', false, $1, now(), now()) ON CONFLICT DO NOTHING`,
		agentID, orgID); err != nil {
		t.Fatalf("seed agent: %v", err)
	}
	key := "key-store-" + t.Name()
	id := "sess-store-" + t.Name()
	if _, err := store.Insert(ctx, session.Session{
		ID: id, AgentID: agentID, Channel: "chat", Status: "pending",
		StripePaymentIntentID: "pi_store_" + t.Name(),
		Currency:              "usd", StartedAt: time.Now().UTC(),
		IdempotencyKey: key,
	}); err != nil {
		t.Fatalf("insert: %v", err)
	}
	t.Cleanup(func() {
		db.Exec(ctx, `DELETE FROM sessions WHERE id=$1`, id)
		db.Exec(ctx, `DELETE FROM agents WHERE id=$1`, agentID)
		db.Exec(ctx, `DELETE FROM orgs WHERE id=$1`, orgID)
	})

	got, err := store.GetByIdempotencyKey(ctx, key)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.ID != id {
		t.Errorf("id: got %q, want %q", got.ID, id)
	}
}

// TestCreateSession_IdempotencyKeyTooLong verifies that a POST with an
// Idempotency-Key longer than 255 chars is rejected with 400 and no session
// row is created. This mirrors the documented cap (maxIdempotencyKeyLen = 255)
// that matches Stripe's own limit.
func TestCreateSession_IdempotencyKeyTooLong(t *testing.T) {
	db := setupTestDBForIdempotency(t)
	ctx := context.Background()

	// Seed org + agent for the request body (even though we expect a 400 before
	// any DB insert, the handler decodes the body first so we need a valid one).
	orgID := "org-len-" + t.Name()
	agentID := "agent-len-" + t.Name()
	if _, err := db.Exec(ctx,
		`INSERT INTO orgs (id, name, slug, created_at) VALUES ($1,$1,$1,now()) ON CONFLICT DO NOTHING`,
		orgID); err != nil {
		t.Fatalf("seed org: %v", err)
	}
	if _, err := db.Exec(ctx, `
		INSERT INTO agents (id, org_id, name, business_type, system_prompt, tools, voice_enabled, embed_token, created_at, updated_at)
		VALUES ($1, $2, 'test', 'custom', '', '{}', false, $1, now(), now()) ON CONFLICT DO NOTHING`,
		agentID, orgID); err != nil {
		t.Fatalf("seed agent: %v", err)
	}
	t.Cleanup(func() {
		db.Exec(ctx, `DELETE FROM agents WHERE id=$1`, agentID)
		db.Exec(ctx, `DELETE FROM orgs WHERE id=$1`, orgID)
	})

	// Build a key that is exactly 256 chars (one over the 255 limit).
	longKey := strings.Repeat("k", 256)

	router := session.Router(db, stripeKeyForTest)
	body := `{"agent_id":"` + agentID + `","amount_cents":100,"currency":"usd"}`
	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", longKey)
	w := httptest.NewRecorder()

	router.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("status: got %d, want 400; body=%s", w.Code, w.Body.String())
	}

	// Confirm no session row was created for this over-length key.
	var n int
	if err := db.QueryRow(ctx,
		`SELECT count(*) FROM sessions WHERE idempotency_key=$1`, longKey).Scan(&n); err != nil {
		t.Fatalf("count: %v", err)
	}
	if n != 0 {
		t.Errorf("session row created despite 400: count=%d, want 0", n)
	}
}

func setupTestDBForIdempotency(t *testing.T) *pgxpool.Pool {
	t.Helper()
	// Defer to the existing testDB helper convention in store_test.go.
	return testDB(t)
}
