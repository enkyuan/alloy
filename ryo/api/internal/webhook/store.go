package webhook

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Webhook is a registered merchant endpoint.
type Webhook struct {
	ID        string    `json:"id"`
	OrgID     string    `json:"org_id"`
	URL       string    `json:"url"`
	Secret    string    `json:"-"` // never serialised to clients after creation
	Events    []string  `json:"events"`
	CreatedAt time.Time `json:"created_at"`
}

// Delivery is a queued or completed event push.
type Delivery struct {
	ID          string
	WebhookID   string
	EventType   string
	Payload     []byte
	Status      string
	Attempts    int
	NextAttempt time.Time
	LastStatus  *int
}

// Store handles webhook and delivery persistence.
type Store struct {
	db *pgxpool.Pool
}

type scanner interface {
	Scan(dest ...any) error
}

// Querier is satisfied by both *pgxpool.Pool and pgx.Tx, allowing store
// methods to be shared between pool-level and tx-scoped calls without
// duplicating SQL.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	Exec(ctx context.Context, sql string, args ...any) (pgconn.CommandTag, error)
}

// NewStore creates a Store backed by db.
func NewStore(db *pgxpool.Pool) *Store {
	return &Store{db: db}
}

// Insert saves a new webhook registration.
func (s *Store) Insert(ctx context.Context, wh Webhook) (Webhook, error) {
	row := s.db.QueryRow(ctx, `
		INSERT INTO webhooks (id, org_id, url, secret, events, created_at)
		VALUES ($1, $2, $3, $4, $5, $6)
		RETURNING id, org_id, url, secret, events, created_at`,
		wh.ID, wh.OrgID, wh.URL, wh.Secret, wh.Events, wh.CreatedAt,
	)
	return scanWebhook(row)
}

// GetByID fetches a webhook by primary key.
func (s *Store) GetByID(ctx context.Context, id string) (Webhook, error) {
	row := s.db.QueryRow(ctx,
		`SELECT id, org_id, url, secret, events, created_at FROM webhooks WHERE id = $1`, id)
	return scanWebhook(row)
}

// List returns all webhooks for an org.
func (s *Store) List(ctx context.Context, orgID string) ([]Webhook, error) {
	rows, err := s.db.Query(ctx,
		`SELECT id, org_id, url, secret, events, created_at FROM webhooks WHERE org_id = $1 ORDER BY created_at DESC`,
		orgID)
	if err != nil {
		return nil, fmt.Errorf("list webhooks: %w", err)
	}
	defer rows.Close()
	var out []Webhook
	for rows.Next() {
		wh, err := scanWebhook(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, wh)
	}
	return out, rows.Err()
}

// Delete removes a webhook by ID and orgID.
func (s *Store) Delete(ctx context.Context, id, orgID string) error {
	_, err := s.db.Exec(ctx, `DELETE FROM webhooks WHERE id = $1 AND org_id = $2`, id, orgID)
	return err
}

// ListForEvent returns all webhooks for an org that subscribe to eventType.
func (s *Store) ListForEvent(ctx context.Context, orgID, eventType string) ([]Webhook, error) {
	rows, err := s.db.Query(ctx, `
		SELECT id, org_id, url, secret, events, created_at
		FROM webhooks
		WHERE org_id = $1 AND ($2 = ANY(events) OR cardinality(events) = 0)
		ORDER BY created_at DESC`, orgID, eventType)
	if err != nil {
		return nil, fmt.Errorf("list webhooks for event: %w", err)
	}
	defer rows.Close()
	var out []Webhook
	for rows.Next() {
		wh, err := scanWebhook(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, wh)
	}
	return out, rows.Err()
}

// ListAllForEvent returns all webhooks subscribed to eventType across all orgs.
func (s *Store) ListAllForEvent(ctx context.Context, eventType string) ([]Webhook, error) {
	return listAllForEventImpl(ctx, s.db, eventType)
}

// ListAllForEventTx is ListAllForEvent scoped to an existing transaction.
func (s *Store) ListAllForEventTx(ctx context.Context, tx pgx.Tx, eventType string) ([]Webhook, error) {
	return listAllForEventImpl(ctx, tx, eventType)
}

func listAllForEventImpl(ctx context.Context, q Querier, eventType string) ([]Webhook, error) {
	rows, err := q.Query(ctx, `
		SELECT id, org_id, url, secret, events, created_at
		FROM webhooks
		WHERE $1 = ANY(events) OR cardinality(events) = 0`, eventType)
	if err != nil {
		return nil, fmt.Errorf("list all for event: %w", err)
	}
	defer rows.Close()
	var out []Webhook
	for rows.Next() {
		wh, err := scanWebhook(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, wh)
	}
	return out, rows.Err()
}

// InsertDelivery enqueues a new delivery row (status: pending).
func (s *Store) InsertDelivery(ctx context.Context, d Delivery) error {
	return insertDeliveryImpl(ctx, s.db, d)
}

// InsertDeliveryTx is InsertDelivery scoped to an existing transaction.
func (s *Store) InsertDeliveryTx(ctx context.Context, tx pgx.Tx, d Delivery) error {
	return insertDeliveryImpl(ctx, tx, d)
}

func insertDeliveryImpl(ctx context.Context, q Querier, d Delivery) error {
	_, err := q.Exec(ctx, `
		INSERT INTO webhook_deliveries
		  (id, webhook_id, event_type, payload, status, attempts, next_attempt, created_at)
		VALUES ($1, $2, $3, $4, 'pending', 0, $5, now())`,
		d.ID, d.WebhookID, d.EventType, d.Payload, d.NextAttempt,
	)
	return err
}

// PollPending fetches up to limit pending deliveries due now.
func (s *Store) PollPending(ctx context.Context, limit int) ([]Delivery, error) {
	rows, err := s.db.Query(ctx, `
		SELECT id, webhook_id, event_type, payload, status, attempts, next_attempt, last_status
		FROM webhook_deliveries
		WHERE status = 'pending' AND next_attempt <= now()
		ORDER BY next_attempt
		LIMIT $1
		FOR UPDATE SKIP LOCKED`, limit)
	if err != nil {
		return nil, fmt.Errorf("poll pending: %w", err)
	}
	defer rows.Close()
	var out []Delivery
	for rows.Next() {
		var d Delivery
		if err := rows.Scan(&d.ID, &d.WebhookID, &d.EventType, &d.Payload,
			&d.Status, &d.Attempts, &d.NextAttempt, &d.LastStatus); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

// MarkDelivered sets status to delivered.
func (s *Store) MarkDelivered(ctx context.Context, id string, httpStatus int) error {
	_, err := s.db.Exec(ctx,
		`UPDATE webhook_deliveries SET status='delivered', last_status=$2 WHERE id=$1`,
		id, httpStatus)
	return err
}

// MarkFailed increments attempts, sets next retry time, or marks dead after 3.
func (s *Store) MarkFailed(ctx context.Context, id string, httpStatus *int, attempts int) error {
	var nextAttempt time.Time
	var newStatus string
	switch attempts {
	case 1:
		nextAttempt = time.Now().UTC().Add(30 * time.Second)
		newStatus = "failed"
	case 2:
		nextAttempt = time.Now().UTC().Add(5 * time.Minute)
		newStatus = "failed"
	default:
		nextAttempt = time.Now().UTC()
		newStatus = "dead"
	}
	_, err := s.db.Exec(ctx, `
		UPDATE webhook_deliveries
		SET status=$2, attempts=$3, next_attempt=$4, last_status=$5
		WHERE id=$1`,
		id, newStatus, attempts, nextAttempt, httpStatus)
	return err
}

func scanWebhook(row scanner) (Webhook, error) {
	var wh Webhook
	err := row.Scan(&wh.ID, &wh.OrgID, &wh.URL, &wh.Secret, &wh.Events, &wh.CreatedAt)
	if err != nil {
		if err == pgx.ErrNoRows {
			return Webhook{}, fmt.Errorf("webhook not found")
		}
		return Webhook{}, fmt.Errorf("scan webhook: %w", err)
	}
	return wh, nil
}
