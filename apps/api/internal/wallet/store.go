package wallet

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type walletStore struct {
	db *pgxpool.Pool
}

func newStore(db *pgxpool.Pool) *walletStore {
	return &walletStore{db: db}
}

func (s *walletStore) insert(ctx context.Context, w Wallet) (Wallet, error) {
	row := s.db.QueryRow(ctx, `
		INSERT INTO wallets (id, org_id, provider, external_id, status, currency, kyb_required, kyb_portal_url, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)
		RETURNING id, org_id, provider, external_id, status, balance_cents, currency, kyb_required, kyb_portal_url, created_at`,
		w.ID, w.OrgID, w.Provider, nilIfEmpty(w.ExternalID), w.Status, w.Currency, w.KYBRequired, nilIfEmpty(w.KYBPortalURL), time.Now().UTC(),
	)
	return scanWallet(row)
}

func (s *walletStore) get(ctx context.Context, id, orgID string) (Wallet, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, org_id, provider, external_id, status, balance_cents, currency, kyb_required, kyb_portal_url, created_at
		FROM wallets WHERE id = $1 AND org_id = $2`, id, orgID)
	return scanWallet(row)
}

func (s *walletStore) getByOrg(ctx context.Context, orgID string) (Wallet, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, org_id, provider, external_id, status, balance_cents, currency, kyb_required, kyb_portal_url, created_at
		FROM wallets WHERE org_id = $1 ORDER BY created_at DESC LIMIT 1`, orgID)
	return scanWallet(row)
}

type scanner interface {
	Scan(dest ...any) error
}

func scanWallet(row scanner) (Wallet, error) {
	var w Wallet
	var externalID, kybPortalURL *string
	err := row.Scan(&w.ID, &w.OrgID, &w.Provider, &externalID, &w.Status, &w.BalanceCents, &w.Currency, &w.KYBRequired, &kybPortalURL, &w.CreatedAt)
	if err != nil {
		if err == pgx.ErrNoRows {
			return Wallet{}, fmt.Errorf("not found")
		}
		return Wallet{}, fmt.Errorf("scan wallet: %w", err)
	}
	if externalID != nil {
		w.ExternalID = *externalID
	}
	if kybPortalURL != nil {
		w.KYBPortalURL = *kybPortalURL
	}
	return w, nil
}

func nilIfEmpty(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
