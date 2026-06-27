package stripehandler

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/ryo/api/internal/session"
	"github.com/enkyuan/alloy/ryo/api/internal/webhook"
)

// White-box tests for applyAndEnqueue.
// Lives in package stripehandler (no _test suffix on the package) so we can
// call the unexported method directly without widening the public API.

// internalTestDB mirrors testDB in handler_tx_test.go. The duplication is
// intentional: this file is in package stripehandler (white-box, no _test
// suffix) while handler_tx_test.go is in package stripehandler_test. Go does
// not allow sharing helpers across those two test packages in the same
// directory, so each must define its own DB setup helper.
func internalTestDB(t *testing.T) *pgxpool.Pool {
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

// seedOrgAgentSession returns (orgID, agentID, piID, sessID) with cleanup wired.
func seedOrgAgentSession(t *testing.T, db *pgxpool.Pool, suffix string) (string, string, string, string) {
	t.Helper()
	ctx := context.Background()
	orgID := "org-" + suffix
	if _, err := db.Exec(ctx,
		`INSERT INTO orgs (id, name, slug, created_at) VALUES ($1,$1,$1,now()) ON CONFLICT DO NOTHING`,
		orgID); err != nil {
		t.Fatalf("seed org: %v", err)
	}
	agentID := "agent-" + suffix
	if _, err := db.Exec(ctx, `
		INSERT INTO agents (id, org_id, name, business_type, system_prompt, tools, voice_enabled, embed_token, created_at, updated_at)
		VALUES ($1, $2, 'test', 'custom', '', '{}', false, $1, now(), now()) ON CONFLICT DO NOTHING`,
		agentID, orgID); err != nil {
		t.Fatalf("seed agent: %v", err)
	}
	piID := "pi_" + suffix
	sessID := "sess-" + suffix
	sessStore := session.NewStore(db)
	if _, err := sessStore.Insert(ctx, session.Session{
		ID: sessID, AgentID: agentID, Channel: "chat", Status: "pending",
		StripePaymentIntentID: piID, Currency: "usd", StartedAt: time.Now().UTC(),
	}); err != nil {
		t.Fatalf("seed session: %v", err)
	}
	t.Cleanup(func() {
		db.Exec(ctx, `DELETE FROM webhook_deliveries WHERE webhook_id IN (SELECT id FROM webhooks WHERE org_id=$1)`, orgID)
		db.Exec(ctx, `DELETE FROM webhooks WHERE org_id=$1`, orgID)
		db.Exec(ctx, `DELETE FROM sessions WHERE id=$1`, sessID)
		db.Exec(ctx, `DELETE FROM agents WHERE id=$1`, agentID)
		db.Exec(ctx, `DELETE FROM processed_stripe_events WHERE event_id LIKE 'evt_' || $1 || '%'`, suffix)
		db.Exec(ctx, `DELETE FROM orgs WHERE id=$1`, orgID)
	})
	return orgID, agentID, piID, sessID
}

func seedWebhook(t *testing.T, db *pgxpool.Pool, orgID, eventType string) string {
	t.Helper()
	ctx := context.Background()
	whID := "wh-" + orgID + "-" + eventType
	if _, err := db.Exec(ctx, `
		INSERT INTO webhooks (id, org_id, url, secret, events, created_at)
		VALUES ($1, $2, 'https://example.test/hook', 'sec', $3, now())
		ON CONFLICT DO NOTHING`,
		whID, orgID, []string{eventType}); err != nil {
		t.Fatalf("seed webhook: %v", err)
	}
	return whID
}

// TestApplyAndEnqueue_HappyPathCommits drives the orchestrator end-to-end and
// asserts both side-effects landed: session is "completed" AND a delivery row
// exists for the merchant's webhook.
func TestApplyAndEnqueue_HappyPathCommits(t *testing.T) {
	db := internalTestDB(t)
	ctx := context.Background()
	orgID, _, piID, sessID := seedOrgAgentSession(t, db, "applyok_"+t.Name())
	whID := seedWebhook(t, db, orgID, "payment.completed")

	h := New("whsec_unused_in_this_test", session.NewStore(db), webhook.NewStore(db), db)

	err := h.applyAndEnqueue(ctx, "evt_applyok_"+t.Name(), "payment_intent.succeeded",
		piID, "completed", "ok", 250, "payment.completed",
		map[string]any{"amount_cents": int64(250), "currency": "usd", "status": "completed"})
	if err != nil {
		t.Fatalf("applyAndEnqueue: %v", err)
	}

	// Session updated.
	got, err := session.NewStore(db).GetByPaymentIntent(ctx, piID)
	if err != nil {
		t.Fatalf("get session: %v", err)
	}
	if got.Status != "completed" {
		t.Errorf("status: got %q, want completed", got.Status)
	}
	if got.ID != sessID {
		t.Errorf("session id: got %q, want %q", got.ID, sessID)
	}

	// Delivery row inserted.
	var n int
	if err := db.QueryRow(ctx,
		`SELECT count(*) FROM webhook_deliveries WHERE webhook_id=$1 AND event_type='payment.completed'`,
		whID).Scan(&n); err != nil {
		t.Fatalf("count deliveries: %v", err)
	}
	if n != 1 {
		t.Errorf("delivery count: got %d, want 1", n)
	}
}

// TestApplyAndEnqueue_DedupSkipsDuplicate proves the same event.ID processed
// twice produces ONE delivery row, not two — the exact bug Stripe's retry
// behavior would otherwise trigger now that we return 500 on internal errors.
func TestApplyAndEnqueue_DedupSkipsDuplicate(t *testing.T) {
	db := internalTestDB(t)
	ctx := context.Background()
	orgID, _, piID, _ := seedOrgAgentSession(t, db, "dedup_"+t.Name())
	whID := seedWebhook(t, db, orgID, "payment.completed")

	h := New("whsec_unused_in_this_test", session.NewStore(db), webhook.NewStore(db), db)
	eventID := "evt_dedup_" + t.Name()

	for i := 0; i < 2; i++ {
		if err := h.applyAndEnqueue(ctx, eventID, "payment_intent.succeeded",
			piID, "completed", "ok", 250, "payment.completed",
			map[string]any{"amount_cents": int64(250)}); err != nil {
			t.Fatalf("applyAndEnqueue iter %d: %v", i, err)
		}
	}

	var n int
	if err := db.QueryRow(ctx,
		`SELECT count(*) FROM webhook_deliveries WHERE webhook_id=$1`, whID).Scan(&n); err != nil {
		t.Fatalf("count: %v", err)
	}
	if n != 1 {
		t.Errorf("delivery count after duplicate event: got %d, want 1 (dedup failed)", n)
	}

	var seen int
	if err := db.QueryRow(ctx,
		`SELECT count(*) FROM processed_stripe_events WHERE event_id=$1`, eventID).Scan(&seen); err != nil {
		t.Fatalf("count processed_stripe_events: %v", err)
	}
	if seen != 1 {
		t.Errorf("processed_stripe_events count: got %d, want 1", seen)
	}
}
