package stripehandler_test

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/ryo/api/internal/session"
	"github.com/enkyuan/alloy/ryo/api/internal/webhook"
)

// testDB mirrors internalTestDB in handler_internal_test.go. The duplication
// is intentional: this file is in package stripehandler_test (black-box) while
// handler_internal_test.go is in package stripehandler. Go does not allow
// sharing helpers across those two test packages in the same directory.
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

// TestUpdateAfterPaymentTx_RollsBackOnDeliveryFailure proves the bug fix:
// if any insert inside the tx fails, the session row's status must NOT be
// updated. Pre-fix, the update would have committed before the failure point.
func TestUpdateAfterPaymentTx_RollsBackOnDeliveryFailure(t *testing.T) {
	ctx := context.Background()
	db := testDB(t)
	sessStore := session.NewStore(db)
	whStore := webhook.NewStore(db)

	// Seed org + agent so the session FK is satisfied.
	orgID := "org-tx-" + t.Name()
	if _, err := db.Exec(ctx,
		`INSERT INTO orgs (id, name, slug, created_at) VALUES ($1,$1,$1,now()) ON CONFLICT DO NOTHING`,
		orgID); err != nil {
		t.Fatalf("seed org: %v", err)
	}
	agentID := "agent-tx-" + t.Name()
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

	piID := "pi_tx_test_" + t.Name()
	seeded, err := sessStore.Insert(ctx, session.Session{
		ID:                    "sess-tx-" + t.Name(),
		AgentID:               agentID,
		Channel:               "chat",
		Status:                "pending",
		StripePaymentIntentID: piID,
		Currency:              "usd",
		StartedAt:             time.Now().UTC(),
	})
	if err != nil {
		t.Fatalf("seed session: %v", err)
	}
	t.Cleanup(func() {
		db.Exec(ctx, `DELETE FROM webhook_deliveries WHERE webhook_id IN (SELECT id FROM webhooks WHERE org_id=$1)`, orgID)
		db.Exec(ctx, `DELETE FROM sessions WHERE id=$1`, seeded.ID)
	})

	// Begin a tx and drive the same sequence the handler drives.
	tx, err := db.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}

	if err := sessStore.UpdateAfterPaymentTx(ctx, tx, piID, "completed", "summary", 100); err != nil {
		_ = tx.Rollback(ctx)
		t.Fatalf("update session: %v", err)
	}

	// Force a delivery insert failure via an FK violation: webhook_id "missing"
	// does not exist, so the row violates webhook_deliveries.webhook_id FK.
	err = whStore.InsertDeliveryTx(ctx, tx, webhook.Delivery{
		ID:          "d-fk-violation",
		WebhookID:   "wh-does-not-exist",
		EventType:   "payment.completed",
		Payload:     []byte(`{}`),
		NextAttempt: time.Now().UTC(),
	})
	if err == nil {
		_ = tx.Rollback(ctx)
		t.Fatal("expected FK violation, got nil")
	}
	if err := tx.Rollback(ctx); err != nil {
		t.Fatalf("rollback: %v", err)
	}

	// Session must still be pending — the update rolled back.
	got, err := sessStore.GetByPaymentIntent(ctx, piID)
	if err != nil {
		t.Fatalf("get session: %v", err)
	}
	if got.Status != "pending" {
		t.Errorf("status: got %q, want pending (rolled back)", got.Status)
	}
}

// TestUpdateAfterPaymentTx_CommitsOnSuccess proves the happy path: when
// nothing in the tx fails, the session update sticks.
func TestUpdateAfterPaymentTx_CommitsOnSuccess(t *testing.T) {
	ctx := context.Background()
	db := testDB(t)
	sessStore := session.NewStore(db)

	orgID := "org-tx-ok-" + t.Name()
	if _, err := db.Exec(ctx,
		`INSERT INTO orgs (id, name, slug, created_at) VALUES ($1,$1,$1,now()) ON CONFLICT DO NOTHING`,
		orgID); err != nil {
		t.Fatalf("seed org: %v", err)
	}
	agentID := "agent-tx-ok-" + t.Name()
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

	piID := "pi_tx_ok_" + t.Name()
	seeded, err := sessStore.Insert(ctx, session.Session{
		ID:                    "sess-tx-ok-" + t.Name(),
		AgentID:               agentID,
		Channel:               "chat",
		Status:                "pending",
		StripePaymentIntentID: piID,
		Currency:              "usd",
		StartedAt:             time.Now().UTC(),
	})
	if err != nil {
		t.Fatalf("seed session: %v", err)
	}
	t.Cleanup(func() { db.Exec(ctx, `DELETE FROM sessions WHERE id=$1`, seeded.ID) })

	tx, err := db.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	if err := sessStore.UpdateAfterPaymentTx(ctx, tx, piID, "completed", "ok", 100); err != nil {
		_ = tx.Rollback(ctx)
		t.Fatalf("update: %v", err)
	}
	if err := tx.Commit(ctx); err != nil {
		t.Fatalf("commit: %v", err)
	}

	got, err := sessStore.GetByPaymentIntent(ctx, piID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.Status != "completed" {
		t.Errorf("status: got %q, want completed", got.Status)
	}
	if got.AmountCollectedCents != 100 {
		t.Errorf("amount: got %d, want 100", got.AmountCollectedCents)
	}
}
