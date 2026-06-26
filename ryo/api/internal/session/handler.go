package session

import (
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	stripe "github.com/stripe/stripe-go/v82"
	"github.com/stripe/stripe-go/v82/paymentintent"

	"github.com/enkyuan/alloy/ryo/api/internal/middleware"
)

// maxIdempotencyKeyLen caps the Idempotency-Key header to match Stripe's
// documented 255-char limit. Longer keys would round-trip to Stripe and
// surface as a less-informative 400 than the one we return here.
const maxIdempotencyKeyLen = 255

// CreateSessionRequest is the payload sent by the kaji request_payment tool.
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

	// Idempotency replay: if the caller supplies an Idempotency-Key we've
	// already used, return the original session instead of creating a new
	// PaymentIntent. This is the FIRST thing we do — before any Stripe call —
	// so the second attempt never reaches Stripe and never creates an orphan
	// PaymentIntent.
	idemKey := r.Header.Get("Idempotency-Key")
	if len(idemKey) > maxIdempotencyKeyLen {
		writeError(w, http.StatusBadRequest, "Idempotency-Key too long (max 255 chars)")
		return
	}
	if idemKey != "" {
		existing, err := h.store.GetByIdempotencyKey(r.Context(), idemKey)
		switch {
		case err == nil:
			// Replay: re-fetch the PaymentIntent so we can return the same
			// client_secret the original response carried. Otherwise the
			// caller (e.g. the frontend rendering Stripe's Payment Element)
			// has no way to drive the second response forward.
			resp := map[string]any{"session": existing}
			if existing.StripePaymentIntentID != "" {
				if pi, err := paymentintent.Get(existing.StripePaymentIntentID, nil); err == nil {
					resp["client_secret"] = pi.ClientSecret
				}
			}
			writeJSON(w, http.StatusCreated, resp)
			return
		case errors.Is(err, pgx.ErrNoRows):
			// Fall through to normal create path.
		default:
			// Real DB error — do NOT silently fall through to creating a
			// duplicate PaymentIntent. Stripe's IdempotencyKey would dedup
			// on its side, but we'd still leak a half-applied DB state.
			writeError(w, http.StatusServiceUnavailable, "idempotency lookup failed")
			return
		}
	}

	// Create Stripe PaymentIntent. Passing IdempotencyKey here is what makes
	// Stripe itself idempotent: if our DB insert below fails and the client
	// retries with the same Idempotency-Key, Stripe returns the same
	// PaymentIntent rather than creating a duplicate.
	params := &stripe.PaymentIntentParams{
		Amount:   stripe.Int64(req.AmountCents),
		Currency: stripe.String(currency),
	}
	if req.Description != "" {
		params.Description = stripe.String(req.Description)
	}
	if idemKey != "" {
		params.IdempotencyKey = stripe.String(idemKey)
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
		IdempotencyKey:        idemKey,
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
