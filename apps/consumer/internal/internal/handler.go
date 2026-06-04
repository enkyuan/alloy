// Package internal exposes an endpoint called only by @agentpay/api.
// Secured by X-Internal-Secret header rather than consumer JWT.
package internal

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/enkyuan/alloy/apps/consumer/internal/transaction"
)

type handler struct {
	store          *transaction.Store
	internalSecret string
}

// Router mounts the internal write endpoint.
func Router(db *pgxpool.Pool, internalSecret string) http.Handler {
	h := &handler{store: transaction.NewStore(db), internalSecret: internalSecret}
	r := chi.NewRouter()
	r.Use(h.requireSecret)
	r.Post("/transactions", h.writeTransaction)
	return r
}

type writeTransactionRequest struct {
	ConsumerID        string `json:"consumer_id"`
	SessionID         string `json:"session_id"`
	AmountCents       int64  `json:"amount_cents"`
	Currency          string `json:"currency"`
	Status            string `json:"status"`
	MerchantName      string `json:"merchant_name"`
	MerchantID        string `json:"merchant_id"`
	ActionDescription string `json:"action_description"`
}

func (h *handler) requireSecret(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Internal-Secret") != h.internalSecret {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (h *handler) writeTransaction(w http.ResponseWriter, r *http.Request) {
	var req writeTransactionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	if req.ConsumerID == "" || req.SessionID == "" {
		http.Error(w, "consumer_id and session_id required", http.StatusBadRequest)
		return
	}

	currency := req.Currency
	if currency == "" {
		currency = "usd"
	}

	plainLabel := buildPlainLabel(req.MerchantName, req.ActionDescription, req.AmountCents, currency, req.Status)

	tx := transaction.Transaction{
		ID:          uuid.New().String(),
		ConsumerID:  req.ConsumerID,
		SessionID:   req.SessionID,
		AmountCents: req.AmountCents,
		Currency:    currency,
		Status:      req.Status,
		PlainLabel:  plainLabel,
		MerchantID:  req.MerchantID,
		CreatedAt:   time.Now().UTC(),
	}
	created, err := h.store.Insert(r.Context(), tx)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	if err := json.NewEncoder(w).Encode(created); err != nil {
		_ = err
	}
}

// buildPlainLabel generates a human-readable transaction description.
// Format: "Agent at {merchant} {action} - ${amount}" or failure variant.
func buildPlainLabel(merchantName, action string, amountCents int64, currency, status string) string {
	if status == "failed" {
		return "Payment to " + merchantName + " failed - no charge made"
	}
	amount := fmt.Sprintf("%.2f", float64(amountCents)/100)
	sym := currencySymbol(currency)
	if action != "" {
		return "Agent at " + merchantName + " " + action + " - " + sym + amount
	}
	return "Payment to " + merchantName + " - " + sym + amount
}

func currencySymbol(currency string) string {
	switch currency {
	case "usd":
		return "$"
	case "eur":
		return "€"
	case "gbp":
		return "£"
	default:
		return currency + " "
	}
}
