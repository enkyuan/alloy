package payment

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type paymentStore struct {
	db *pgxpool.Pool
}

func newStore(db *pgxpool.Pool) *paymentStore {
	return &paymentStore{db: db}
}

func (s *paymentStore) insert(ctx context.Context, cfg PaymentConfig) (PaymentConfig, error) {
	row := s.db.QueryRow(ctx, `
		INSERT INTO payment_configs
			(id, agent_id, provider, collection_method, require_confirmation, max_auto_charge_amount, currency, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)
		RETURNING id, agent_id, provider, collection_method, require_confirmation, max_auto_charge_amount, currency, created_at`,
		cfg.ID, cfg.AgentID, cfg.Provider, cfg.CollectionMethod, cfg.RequireConfirmation, cfg.MaxAutoChargeAmount, cfg.Currency, time.Now().UTC(),
	)
	return scanConfig(row)
}

func (s *paymentStore) getByAgent(ctx context.Context, agentID string) (PaymentConfig, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, agent_id, provider, collection_method, require_confirmation, max_auto_charge_amount, currency, created_at
		FROM payment_configs WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 1`, agentID)
	return scanConfig(row)
}

type scanner interface {
	Scan(dest ...any) error
}

func scanConfig(row scanner) (PaymentConfig, error) {
	var c PaymentConfig
	err := row.Scan(&c.ID, &c.AgentID, &c.Provider, &c.CollectionMethod, &c.RequireConfirmation, &c.MaxAutoChargeAmount, &c.Currency, &c.CreatedAt)
	if err != nil {
		if err == pgx.ErrNoRows {
			return PaymentConfig{}, fmt.Errorf("not found")
		}
		return PaymentConfig{}, fmt.Errorf("scan payment config: %w", err)
	}
	return c, nil
}
