package wallet

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/ryo/api/internal/middleware"
)

type WalletStatus string

const (
	WalletStatusPending    WalletStatus = "pending"
	WalletStatusVerifying  WalletStatus = "verifying"
	WalletStatusActive     WalletStatus = "active"
	WalletStatusRestricted WalletStatus = "restricted"
)

type Wallet struct {
	ID           string       `json:"id"`
	OrgID        string       `json:"org_id"`
	Provider     string       `json:"provider"`
	ExternalID   string       `json:"external_id,omitempty"`
	Status       WalletStatus `json:"status"`
	BalanceCents int64        `json:"balance_cents"`
	Currency     string       `json:"currency"`
	KYBRequired  bool         `json:"kyb_required"`
	KYBPortalURL string       `json:"kyb_portal_url,omitempty"`
	CreatedAt    time.Time    `json:"created_at"`
}

type CreateWalletRequest struct {
	Provider      string `json:"provider"`
	Currency      string `json:"currency"`
	AutoConfigure bool   `json:"auto_configure"`
	ExternalID    string `json:"external_id"`
}

type handler struct {
	store *walletStore
}

func Router(db *pgxpool.Pool) http.Handler {
	h := &handler{store: newStore(db)}
	r := chi.NewRouter()
	r.Post("/", h.createWallet)
	r.Get("/", h.getWallet)
	r.Get("/balance", h.getBalance)
	r.Get("/transactions", h.listTransactions)
	return r
}

func (h *handler) createWallet(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	var req CreateWalletRequest
	if !middleware.Decode(w, r, &req) {
		return
	}
	if req.Provider == "" {
		req.Provider = "natural"
	}
	if req.Currency == "" {
		req.Currency = "usd"
	}
	wl := Wallet{
		ID:       uuid.New().String(),
		OrgID:    orgID,
		Provider: req.Provider,
		Status:   WalletStatusPending,
		Currency: req.Currency,
	}
	if req.AutoConfigure {
		wl.Status = WalletStatusVerifying
		wl.KYBRequired = true
		wl.KYBPortalURL = "https://verify.natural.co/placeholder"
	} else if req.ExternalID != "" {
		wl.ExternalID = req.ExternalID
		wl.Status = WalletStatusActive
	}
	created, err := h.store.insert(r.Context(), wl)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, created)
}

func (h *handler) getWallet(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	wl, err := h.store.getByOrg(r.Context(), orgID)
	if err != nil {
		if errors.Is(err, errNotFound) || err.Error() == "not found" {
			writeError(w, http.StatusNotFound, "no wallet found")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, wl)
}

func (h *handler) getBalance(w http.ResponseWriter, r *http.Request) {
	orgID := middleware.OrgID(r.Context())
	wl, err := h.store.getByOrg(r.Context(), orgID)
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"balance_cents": 0, "currency": "usd"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"balance_cents": wl.BalanceCents, "currency": wl.Currency})
}

func (h *handler) listTransactions(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, []any{})
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
