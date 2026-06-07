package payment

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/agentpay/api/internal/middleware"
)

type Provider string

const (
	ProviderStripe  Provider = "stripe"
	ProviderNatural Provider = "natural"
	ProviderSquare  Provider = "square"
)

type CollectionMethod string

const (
	CollectionPhoneHandoff CollectionMethod = "phone_handoff"
	CollectionOneTimeLink  CollectionMethod = "one_time_link"
	CollectionWallet       CollectionMethod = "wallet"
	CollectionCardOnFile   CollectionMethod = "card_on_file"
)

type PaymentConfig struct {
	ID                  string           `json:"id"`
	AgentID             string           `json:"agent_id"`
	Provider            Provider         `json:"provider"`
	CollectionMethod    CollectionMethod `json:"collection_method"`
	ProviderAccountID   string           `json:"provider_account_id,omitempty"`
	RequireConfirmation bool             `json:"require_confirmation"`
	MaxAutoChargeAmount float64          `json:"max_auto_charge_amount"`
	Currency            string           `json:"currency"`
	CreatedAt           time.Time        `json:"created_at"`
}

type CreatePaymentConfigRequest struct {
	AgentID             string           `json:"agent_id"          validate:"required"`
	Provider            Provider         `json:"provider"          validate:"required"`
	CollectionMethod    CollectionMethod `json:"collection_method" validate:"required"`
	APIKey              string           `json:"api_key"`
	RequireConfirmation bool             `json:"require_confirmation"`
	MaxAutoChargeAmount float64          `json:"max_auto_charge_amount"`
	Currency            string           `json:"currency"`
}

type handler struct {
	store *paymentStore
}

func Router(db *pgxpool.Pool) http.Handler {
	h := &handler{store: newStore(db)}
	r := chi.NewRouter()
	r.Post("/", h.createPaymentConfig)
	r.Get("/{agent_id}", h.getPaymentConfig)
	r.Patch("/{id}", h.updatePaymentConfig)
	r.Get("/providers", listProviders)
	return r
}

func (h *handler) createPaymentConfig(w http.ResponseWriter, r *http.Request) {
	var req CreatePaymentConfigRequest
	if !middleware.Decode(w, r, &req) {
		return
	}
	if req.Currency == "" {
		req.Currency = "usd"
	}
	cfg := PaymentConfig{
		ID:                  uuid.New().String(),
		AgentID:             req.AgentID,
		Provider:            req.Provider,
		CollectionMethod:    req.CollectionMethod,
		RequireConfirmation: req.RequireConfirmation,
		MaxAutoChargeAmount: req.MaxAutoChargeAmount,
		Currency:            req.Currency,
	}
	created, err := h.store.insert(r.Context(), cfg)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, created)
}

func (h *handler) getPaymentConfig(w http.ResponseWriter, r *http.Request) {
	agentID := chi.URLParam(r, "agent_id")
	cfg, err := h.store.getByAgent(r.Context(), agentID)
	if err != nil {
		if errors.Is(err, errNotFound) || err.Error() == "not found" {
			writeError(w, http.StatusNotFound, "not found")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, cfg)
}

func (h *handler) updatePaymentConfig(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusNoContent)
}

func listProviders(w http.ResponseWriter, _ *http.Request) {
	providers := []map[string]any{
		{"id": "stripe", "name": "Stripe", "fields": []string{"api_key"}, "collection_methods": []string{"card_on_file", "one_time_link"}},
		{"id": "natural", "name": "Natural", "fields": []string{"api_key"}, "collection_methods": []string{"phone_handoff", "one_time_link", "wallet"}},
		{"id": "square", "name": "Square", "fields": []string{"api_key", "location_id"}, "collection_methods": []string{"card_on_file", "one_time_link"}},
	}
	writeJSON(w, http.StatusOK, providers)
}

var errNotFound = errors.New("not found")

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
