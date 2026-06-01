// Package payment handles payment provider configuration and workflow setup.
//
// A PaymentConfig ties a provider (Stripe, Natural, etc.) to an agent,
// and defines the workflow — how the agent requests and collects money:
// phone handoff, one-time link, or direct wallet-to-wallet.
package payment

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

// Provider is a supported payment rail.
type Provider string

const (
	ProviderStripe  Provider = "stripe"
	ProviderNatural Provider = "natural"
	ProviderSquare  Provider = "square"
)

// CollectionMethod is how the agent requests payment from the customer.
type CollectionMethod string

const (
	CollectionPhoneHandoff CollectionMethod = "phone_handoff" // agent reads a link aloud / SMS
	CollectionOneTimeLink  CollectionMethod = "one_time_link" // agent sends a URL
	CollectionWallet       CollectionMethod = "wallet"        // direct Natural-to-Natural
	CollectionCardOnFile   CollectionMethod = "card_on_file"  // charge stored card
)

// PaymentConfig binds a provider + collection method to an agent.
type PaymentConfig struct {
	ID               string           `json:"id"`
	AgentID          string           `json:"agent_id"`
	Provider         Provider         `json:"provider"`
	CollectionMethod CollectionMethod `json:"collection_method"`
	// Provider-specific credentials (stored encrypted, never returned in API responses)
	ProviderAccountID string `json:"provider_account_id,omitempty"`
	// Workflow controls
	RequireConfirmation bool    `json:"require_confirmation"` // agent asks "shall I charge £4.50?"
	MaxAutoChargeAmount float64 `json:"max_auto_charge_amount"` // 0 = always confirm
	Currency            string  `json:"currency"`
	CreatedAt           time.Time `json:"created_at"`
}

type CreatePaymentConfigRequest struct {
	AgentID             string           `json:"agent_id"`
	Provider            Provider         `json:"provider"`
	CollectionMethod    CollectionMethod `json:"collection_method"`
	APIKey              string           `json:"api_key"` // write-only, stored encrypted
	RequireConfirmation bool             `json:"require_confirmation"`
	MaxAutoChargeAmount float64          `json:"max_auto_charge_amount"`
	Currency            string           `json:"currency"`
}

func Router() http.Handler {
	r := chi.NewRouter()
	r.Post("/", createPaymentConfig)
	r.Get("/{agent_id}", getPaymentConfig)
	r.Patch("/{id}", updatePaymentConfig)
	r.Get("/providers", listProviders) // returns supported providers + their required fields
	return r
}

func createPaymentConfig(w http.ResponseWriter, r *http.Request) {
	var req CreatePaymentConfigRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request"}`, http.StatusBadRequest)
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
		CreatedAt:           time.Now().UTC(),
	}

	// TODO: encrypt and persist req.APIKey; store cfg
	// TODO: validate API key against provider

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(cfg)
}

func getPaymentConfig(w http.ResponseWriter, r *http.Request) {
	agentID := chi.URLParam(r, "agent_id")
	_ = agentID
	// TODO: load from store
	http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
}

func updatePaymentConfig(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusNoContent)
}

// listProviders returns the available providers and the fields the Studio
// needs to collect for each (drives the wizard UI).
func listProviders(w http.ResponseWriter, r *http.Request) {
	providers := []map[string]any{
		{
			"id":   "stripe",
			"name": "Stripe",
			"fields": []string{"api_key"},
			"collection_methods": []string{"card_on_file", "one_time_link"},
		},
		{
			"id":   "natural",
			"name": "Natural",
			"fields": []string{"api_key"},
			"collection_methods": []string{"phone_handoff", "one_time_link", "wallet"},
		},
		{
			"id":   "square",
			"name": "Square",
			"fields": []string{"api_key", "location_id"},
			"collection_methods": []string{"card_on_file", "one_time_link"},
		},
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(providers)
}
