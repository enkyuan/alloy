package webhook_test

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/ryo/api/internal/webhook"
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

func TestInsertAndListWebhook(t *testing.T) {
	db := testDB(t)
	orgID := "org-wh-test-" + t.Name()
	if _, err := db.Exec(context.Background(),
		`INSERT INTO orgs (id, name, slug, created_at) VALUES ($1,$1,$1,now()) ON CONFLICT DO NOTHING`, orgID); err != nil {
		t.Fatalf("seed org: %v", err)
	}
	t.Cleanup(func() { db.Exec(context.Background(), `DELETE FROM orgs WHERE id=$1`, orgID) })

	s := webhook.NewStore(db)
	wh := webhook.Webhook{
		ID:        "wh-1",
		OrgID:     orgID,
		URL:       "https://example.com/hook",
		Secret:    "sec",
		Events:    []string{"payment.completed"},
		CreatedAt: time.Now().UTC(),
	}
	created, err := s.Insert(context.Background(), wh)
	if err != nil {
		t.Fatalf("insert: %v", err)
	}
	if created.ID != wh.ID {
		t.Errorf("id mismatch")
	}

	list, err := s.List(context.Background(), orgID)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(list) == 0 {
		t.Fatal("expected at least one webhook")
	}
}

func TestInsertDelivery(t *testing.T) {
	db := testDB(t)
	orgID := "org-del-test-" + t.Name()
	if _, err := db.Exec(context.Background(),
		`INSERT INTO orgs (id, name, slug, created_at) VALUES ($1,$1,$1,now()) ON CONFLICT DO NOTHING`, orgID); err != nil {
		t.Fatalf("seed org: %v", err)
	}
	t.Cleanup(func() { db.Exec(context.Background(), `DELETE FROM orgs WHERE id=$1`, orgID) })

	s := webhook.NewStore(db)
	whID := "wh-del-1"
	if _, err := db.Exec(context.Background(),
		`INSERT INTO webhooks (id,org_id,url,secret,events,created_at) VALUES ($1,$2,'https://x.com','sec','{}',now())`,
		whID, orgID); err != nil {
		t.Fatalf("seed webhook: %v", err)
	}

	d := webhook.Delivery{
		ID:          "del-1",
		WebhookID:   whID,
		EventType:   "payment.completed",
		Payload:     []byte(`{"amount":100}`),
		NextAttempt: time.Now().UTC(),
	}
	if err := s.InsertDelivery(context.Background(), d); err != nil {
		t.Fatalf("insert delivery: %v", err)
	}
}
