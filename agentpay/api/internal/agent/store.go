package agent

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type agentStore struct {
	db *pgxpool.Pool
}

func newStore(db *pgxpool.Pool) *agentStore {
	return &agentStore{db: db}
}

func (s *agentStore) insert(ctx context.Context, a Agent) (Agent, error) {
	row := s.db.QueryRow(ctx, `
		INSERT INTO agents (id, org_id, name, business_type, system_prompt, tools, voice_enabled, embed_token, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9)
		RETURNING id, org_id, name, business_type, system_prompt, tools, voice_enabled, wallet_id, embed_token, created_at`,
		a.ID, a.OrgID, a.Name, a.BusinessType, a.SystemPrompt, a.Tools, a.VoiceEnabled, a.EmbedToken, time.Now().UTC(),
	)
	return scanAgent(row)
}

func (s *agentStore) get(ctx context.Context, id, orgID string) (Agent, error) {
	row := s.db.QueryRow(ctx, `
		SELECT id, org_id, name, business_type, system_prompt, tools, voice_enabled, wallet_id, embed_token, created_at
		FROM agents WHERE id = $1 AND org_id = $2`, id, orgID)
	return scanAgent(row)
}

func (s *agentStore) list(ctx context.Context, orgID string) ([]Agent, error) {
	rows, err := s.db.Query(ctx, `
		SELECT id, org_id, name, business_type, system_prompt, tools, voice_enabled, wallet_id, embed_token, created_at
		FROM agents WHERE org_id = $1 ORDER BY created_at DESC`, orgID)
	if err != nil {
		return nil, fmt.Errorf("list agents: %w", err)
	}
	defer rows.Close()

	var agents []Agent
	for rows.Next() {
		a, err := scanAgent(rows)
		if err != nil {
			return nil, err
		}
		agents = append(agents, a)
	}
	return agents, rows.Err()
}

func (s *agentStore) update(ctx context.Context, id, orgID string, req UpdateAgentRequest) (Agent, error) {
	row := s.db.QueryRow(ctx, `
		UPDATE agents SET
			name          = COALESCE(NULLIF($3, ''), name),
			system_prompt = COALESCE(NULLIF($4, ''), system_prompt),
			voice_enabled = $5,
			updated_at    = now()
		WHERE id = $1 AND org_id = $2
		RETURNING id, org_id, name, business_type, system_prompt, tools, voice_enabled, wallet_id, embed_token, created_at`,
		id, orgID, req.Name, req.SystemPrompt, req.VoiceEnabled,
	)
	return scanAgent(row)
}

func (s *agentStore) delete(ctx context.Context, id, orgID string) error {
	_, err := s.db.Exec(ctx, `DELETE FROM agents WHERE id = $1 AND org_id = $2`, id, orgID)
	return err
}

type scanner interface {
	Scan(dest ...any) error
}

func scanAgent(row scanner) (Agent, error) {
	var a Agent
	var walletID *string
	err := row.Scan(&a.ID, &a.OrgID, &a.Name, &a.BusinessType, &a.SystemPrompt, &a.Tools, &a.VoiceEnabled, &walletID, &a.EmbedToken, &a.CreatedAt)
	if err != nil {
		if err == pgx.ErrNoRows {
			return Agent{}, fmt.Errorf("not found")
		}
		return Agent{}, fmt.Errorf("scan agent: %w", err)
	}
	if walletID != nil {
		a.WalletID = *walletID
	}
	return a, nil
}
