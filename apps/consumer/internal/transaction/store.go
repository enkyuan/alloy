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

type scanner interface {
	Scan(dest ...any) error
}

func scanTx(row scanner) (Transaction, error) {
	var tx Transaction
	err := row.Scan(&tx.ID, &tx.ConsumerID, &tx.SessionID, &tx.AmountCents,
		&tx.Currency, &tx.Status, &tx.PlainLabel, &tx.MerchantID, &tx.CreatedAt)
	if err != nil {
		return Transaction{}, fmt.Errorf("scan transaction: %w", err)
	}
	return tx, nil
}
