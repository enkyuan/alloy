// Package wallet handles wallet creation and auto-configuration.
//
// A Wallet is a Natural (or compatible) account where the business
// receives agent-collected payments.  The Studio can either walk the
// user through KYB manually or trigger an auto-configure flow that
// creates a wallet and initiates KYB verification in the background.
package wallet

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

// WalletStatus tracks where the wallet is in its lifecycle.
type WalletStatus string

const (
	WalletStatusPending    WalletStatus = "pending"     // created, KYB not started
	WalletStatusVerifying  WalletStatus = "verifying"   // KYB in progress
	WalletStatusActive     WalletStatus = "active"      // ready to receive payments
	WalletStatusRestricted WalletStatus = "restricted"  // action required
)

// Wallet is the business's payment receiving account.
type Wallet struct {
	ID          string       `json:"id"`
	AgentID     string       `json:"agent_id"`
	Provider    string       `json:"provider"` // "natural", "stripe_connect", etc.
	ExternalID  string       `json:"external_id,omitempty"` // provider's account ID
	Status      WalletStatus `json:"status"`
	BalanceCents int64       `json:"balance_cents"` // in smallest currency unit
	Currency    string       `json:"currency"`
	// KYB
	KYBRequired  bool   `json:"kyb_required"`
	KYBPortalURL string `json:"kyb_portal_url,omitempty"` // link for user to complete KYB
	CreatedAt    time.Time `json:"created_at"`
}

type CreateWalletRequest struct {
	AgentID  string `json:"agent_id"`
	Provider string `json:"provider"` // defaults to "natural"
	Currency string `json:"currency"` // defaults to "usd"
	// AutoConfigure: if true, the API creates the wallet with the provider
	// and returns a KYB portal URL.  If false, user provides ExternalID.
	AutoConfigure bool   `json:"auto_configure"`
	ExternalID    string `json:"external_id,omitempty"`
}

func Router() http.Handler {
	r := chi.NewRouter()
	r.Post("/", createWallet)
	r.Get("/{agent_id}", getWallet)
	r.Get("/{agent_id}/balance", getBalance)
	r.Get("/{agent_id}/transactions", listTransactions)
	return r
}

func createWallet(w http.ResponseWriter, r *http.Request) {
	var req CreateWalletRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request"}`, http.StatusBadRequest)
		return
	}

	if req.Provider == "" {
		req.Provider = "natural"
	}
	if req.Currency == "" {
		req.Currency = "usd"
	}

	wallet := Wallet{
		ID:       uuid.New().String(),
		AgentID:  req.AgentID,
		Provider: req.Provider,
		Status:   WalletStatusPending,
		Currency: req.Currency,
		CreatedAt: time.Now().UTC(),
	}

	if req.AutoConfigure {
		// TODO: call Natural (or Stripe Connect) API to create the account,
		// retrieve KYB portal URL, and set wallet.ExternalID + wallet.KYBPortalURL
		wallet.Status = WalletStatusVerifying
		wallet.KYBRequired = true
		wallet.KYBPortalURL = "https://verify.natural.co/placeholder" // replaced by real URL
	} else if req.ExternalID != "" {
		wallet.ExternalID = req.ExternalID
		wallet.Status = WalletStatusActive
	}

	// TODO: persist wallet

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(wallet)
}

func getWallet(w http.ResponseWriter, r *http.Request) {
	agentID := chi.URLParam(r, "agent_id")
	_ = agentID
	// TODO: load from store
	http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
}

func getBalance(w http.ResponseWriter, r *http.Request) {
	// TODO: fetch live balance from provider
	resp := map[string]any{"balance_cents": 0, "currency": "usd"}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func listTransactions(w http.ResponseWriter, r *http.Request) {
	// TODO: fetch from provider + local ledger
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode([]any{})
}
