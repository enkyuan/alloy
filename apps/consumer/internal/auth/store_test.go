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
	if err := pool.Ping(context.Background()); err != nil {
		pool.Close()
		t.Fatalf("ping db: %v", err)
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
		t.Errorf("email mismatch: got %q", c.Email)
	}

	got, err := s.GetByEmail(context.Background(), "test@example.com")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.ID != c.ID {
		t.Errorf("id mismatch: got %q want %q", got.ID, c.ID)
	}
	t.Cleanup(func() { db.Exec(context.Background(), `DELETE FROM consumers WHERE id=$1`, c.ID) })
}
