package session_test

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/agentpay/api/internal/session"
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
	if err := pool.Ping(context.Background()); err != nil {
		pool.Close()
		t.Fatalf("ping db: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func TestInsertAndGetSession(t *testing.T) {
	db := testDB(t)
	s := session.NewStore(db)

	// need a real agent_id — seed one
	agentID := seedAgent(t, db)

	sess := session.Session{
		ID:                       "sess-test-1",
		AgentID:                  agentID,
		Channel:                  "chat",
		Status:                   "active",
		StripePaymentIntentID:    "pi_test_123",
		ConsumerStripeCustomerID: "",
		AmountCollectedCents:     0,
		Currency:                 "usd",
		StartedAt:                time.Now().UTC(),
	}

	created, err := s.Insert(context.Background(), sess)
	if err != nil {
		t.Fatalf("insert: %v", err)
	}
	if created.ID != sess.ID {
		t.Errorf("got id %q, want %q", created.ID, sess.ID)
	}

	got, err := s.GetByPaymentIntent(context.Background(), "pi_test_123")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.Channel != "chat" {
		t.Errorf("channel: got %q, want chat", got.Channel)
	}
}

func seedAgent(t *testing.T, db *pgxpool.Pool) string {
	t.Helper()
	// seed a minimal org + agent for FK
	orgID := "org-seed-" + t.Name()
	if _, err := db.Exec(context.Background(),
		`INSERT INTO orgs (id, name, slug, created_at) VALUES ($1, $1, $1, now()) ON CONFLICT DO NOTHING`,
		orgID); err != nil {
		t.Fatalf("seed org: %v", err)
	}
	agentID := "agent-seed-" + t.Name()
	if _, err := db.Exec(context.Background(), `
		INSERT INTO agents (id, org_id, name, business_type, system_prompt, tools, voice_enabled, embed_token, created_at, updated_at)
		VALUES ($1, $2, 'test', 'custom', '', '{}', false, $1, now(), now()) ON CONFLICT DO NOTHING`,
		agentID, orgID); err != nil {
		t.Fatalf("seed agent: %v", err)
	}
	t.Cleanup(func() {
		db.Exec(context.Background(), `DELETE FROM agents WHERE id = $1`, agentID)
		db.Exec(context.Background(), `DELETE FROM orgs WHERE id = $1`, orgID)
	})
	return agentID
}
