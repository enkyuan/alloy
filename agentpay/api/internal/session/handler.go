package session

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	stripe "github.com/stripe/stripe-go/v82"
	"github.com/stripe/stripe-go/v82/paymentintent"

	"github.com/enkyuan/alloy/agentpay/api/internal/middleware"
)

// CreateSessionRequest is the payload sent by the agentkit request_payment tool.
type CreateSessionRequest struct {
	AgentID     string `json:"agent_id"    validate:"required"`
	AmountCents int64  `json:"amount_cents" validate:"required,min=1"`
	Currency    string `json:"currency"`
	Description string `json:"description"`
	Channel     string `json:"channel"`
}

type handler struct {
	store *Store
}

// Router mounts the session routes.
func Router(db *pgxpool.Pool, stripeKey string) http.Handler {
	stripe.Key = stripeKey

	h := &handler{store: NewStore(db)}
	r := chi.NewRouter()
	r.Post("/", h.createSession)
	return r
}

func (h *handler) createSession(w http.ResponseWriter, r *http.Request) {
	var req CreateSessionRequest
	if !middleware.Decode(w, r, &req) {
		return
	}
	currency := req.Currency
	if currency == "" {
		currency = "usd"
	}
	channel := req.Channel
	if channel == "" {
		channel = "chat"
	}

	// Create Stripe PaymentIntent
	params := &stripe.PaymentIntentParams{
		Amount:   stripe.Int64(req.AmountCents),
		Currency: stripe.String(currency),
	}
	if req.Description != "" {
		params.Description = stripe.String(req.Description)
	}
	pi, err := paymentintent.New(params)
	if err != nil {
		writeError(w, http.StatusBadGateway, "stripe error: "+err.Error())
		return
	}

	sess := Session{
		ID:                    uuid.New().String(),
		AgentID:               req.AgentID,
		Channel:               channel,
		Status:                "pending",
		StripePaymentIntentID: pi.ID,
		AmountCollectedCents:  req.AmountCents,
		Currency:              currency,
	}
	sess.StartedAt = nowUTC()

	created, err := h.store.Insert(r.Context(), sess)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"session":       created,
		"client_secret": pi.ClientSecret,
	})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := encodeJSON(w, v); err != nil {
		// Headers already written; log only
		_ = err
	}
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
