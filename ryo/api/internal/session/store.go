package session

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Session is a single payment conversation.
type Session struct {
	ID                       string    `json:"id"`
	AgentID                  string    `json:"agent_id"`
	Channel                  string    `json:"channel"`
	Status                   string    `json:"status"`
	StripePaymentIntentID    string    `json:"stripe_payment_intent_id,omitempty"`
	ConsumerStripeCustomerID string    `json:"consumer_stripe_customer_id,omitempty"`
	PlainSummary             string    `json:"plain_summary,omitempty"`
	AmountCollectedCents     int64     `json:"amount_collected_cents"`
	Currency                 string    `json:"currency"`
	StartedAt                time.Time `json:"started_at"`
	// IdempotencyKey is the client-supplied Idempotency-Key header value.
	// Never serialised back to clients; stored only to detect replays.
	IdempotencyKey string `json:"-"`
}

type scanner interface {
	Scan(dest ...any) error
}

// Store handles session persistence.
type Store struct {
	db *pgxpool.Pool
}

// NewStore creates a Store backed by db.
func NewStore(db *pgxpool.Pool) *Store {
	return &Store{db: db}
}

// Insert writes a new session row and returns it.
func (s *Store) Insert(ctx context.Context, sess Session) (Session, error) {
	row := s.db.QueryRow(ctx, `
		INSERT INTO sessions
		  (id, agent_id, channel, status, stripe_payment_intent_id,
		   consumer_stripe_customer_id, amount_collected_cents, currency, started_at,
		   idempotency_key)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
		RETURNING id, agent_id, channel, status, stripe_payment_intent_id,
		          consumer_stripe_customer_id, plain_summary,
		          amount_collected_cents, currency, started_at`,
		sess.ID, sess.AgentID, sess.Channel, sess.Status,
		nullableStr(sess.StripePaymentIntentID),
		nullableStr(sess.ConsumerStripeCustomerID),
		sess.AmountCollectedCents, sess.Currency, sess.StartedAt,
		nullableStr(sess.IdempotencyKey),
	)
	return scanSession(row)
}

// GetByIdempotencyKey returns the session previously inserted under key, or
// pgx.ErrNoRows if there is no such session. Used to make POST /v1/sessions
// idempotent on retry.
func (s *Store) GetByIdempotencyKey(ctx context.Context, key string) (Session, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, agent_id, channel, status, stripe_payment_intent_id,
		       consumer_stripe_customer_id, plain_summary,
		       amount_collected_cents, currency, started_at
		FROM sessions WHERE idempotency_key = $1`, key)
	return scanSession(row)
}

// GetByPaymentIntent fetches the session matching a Stripe PaymentIntent ID.
func (s *Store) GetByPaymentIntent(ctx context.Context, piID string) (Session, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, agent_id, channel, status, stripe_payment_intent_id,
		       consumer_stripe_customer_id, plain_summary,
		       amount_collected_cents, currency, started_at
		FROM sessions WHERE stripe_payment_intent_id = $1`, piID)
	return scanSession(row)
}

// UpdateAfterPayment sets status, plain_summary, and amount after Stripe confirms.
func (s *Store) UpdateAfterPayment(ctx context.Context, piID, status, plainSummary string, amountCents int64) error {
	_, err := s.db.Exec(ctx, `
		UPDATE sessions
		SET status = $2, plain_summary = $3, amount_collected_cents = $4
		WHERE stripe_payment_intent_id = $1`,
		piID, status, plainSummary, amountCents)
	return err
}

// UpdateAfterPaymentTx is UpdateAfterPayment scoped to an existing transaction.
func (s *Store) UpdateAfterPaymentTx(ctx context.Context, tx pgx.Tx, piID, status, plainSummary string, amountCents int64) error {
	_, err := tx.Exec(ctx, `
		UPDATE sessions
		SET status = $2, plain_summary = $3, amount_collected_cents = $4
		WHERE stripe_payment_intent_id = $1`,
		piID, status, plainSummary, amountCents)
	return err
}

// GetByPaymentIntentTx fetches the session matching a Stripe PaymentIntent ID inside a tx.
func (s *Store) GetByPaymentIntentTx(ctx context.Context, tx pgx.Tx, piID string) (Session, error) {
	row := tx.QueryRow(ctx, `
		SELECT id, agent_id, channel, status, stripe_payment_intent_id,
		       consumer_stripe_customer_id, plain_summary,
		       amount_collected_cents, currency, started_at
		FROM sessions WHERE stripe_payment_intent_id = $1`, piID)
	return scanSession(row)
}

func scanSession(row scanner) (Session, error) {
	var sess Session
	var piID, custID, summary *string
	err := row.Scan(
		&sess.ID, &sess.AgentID, &sess.Channel, &sess.Status,
		&piID, &custID, &summary,
		&sess.AmountCollectedCents, &sess.Currency, &sess.StartedAt,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			// Wrap so callers can use errors.Is(err, pgx.ErrNoRows) to
			// distinguish "no such row" from real DB failures.
			return Session{}, fmt.Errorf("session not found: %w", pgx.ErrNoRows)
		}
		return Session{}, fmt.Errorf("scan session: %w", err)
	}
	if piID != nil {
		sess.StripePaymentIntentID = *piID
	}
	if custID != nil {
		sess.ConsumerStripeCustomerID = *custID
	}
	if summary != nil {
		sess.PlainSummary = *summary
	}
	return sess, nil
}

func nullableStr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func nowUTC() time.Time { return time.Now().UTC() }

func encodeJSON(w io.Writer, v any) error {
	return json.NewEncoder(w).Encode(v)
}
