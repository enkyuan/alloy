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

type scanner interface {
	Scan(dest ...any) error
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

func scanConsumer(row scanner) (Consumer, error) {
	var c Consumer
	var custID *string
	err := row.Scan(&c.ID, &c.Email, &c.HashedPassword, &custID, &c.CreatedAt)
	if err != nil {
		if err == pgx.ErrNoRows {
			return Consumer{}, fmt.Errorf("consumer not found")
		}
		return Consumer{}, fmt.Errorf("scan consumer: %w", err)
	}
	if custID != nil {
		c.StripeCustomerID = *custID
	}
	return c, nil
}
