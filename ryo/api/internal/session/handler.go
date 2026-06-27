package session

import (
	"errors"
	"fmt"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
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
			// Mismatch check: if the caller reuses an Idempotency-Key with
			// different contract fields, reject with 422 before replaying.
			// Description is intentionally excluded — it is freeform metadata
			// and mirrors Stripe's behaviour of allowing it to differ.
			if mismatch := checkIdempotencyMismatch(&req, currency, channel, existing); mismatch != "" {
				writeError(w, http.StatusUnprocessableEntity, mismatch)
				return
			}
			// Replay: re-fetch the PaymentIntent so we can return the same
			// client_secret the original response carried. Otherwise the
			// caller (e.g. the frontend rendering Stripe's Payment Element)
			// has no way to drive the second response forward.
			h.writeReplay(w, existing)
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
		// Concurrent race: two requests with the same new Idempotency-Key
		// both missed the GetByIdempotencyKey lookup, both called Stripe
		// (Stripe deduped them), and both tried to INSERT. The second hits
		// the unique constraint on idempotency_key (code 23505). Re-read
		// the row that the first request committed and return it.
		var pgErr *pgconn.PgError
		if idemKey != "" && errors.As(err, &pgErr) && pgErr.Code == "23505" {
			existing, getErr := h.store.GetByIdempotencyKey(r.Context(), idemKey)
			if getErr != nil {
				writeError(w, http.StatusInternalServerError, "idempotency race recovery failed")
				return
			}
			h.writeReplay(w, existing)
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"session":       created,
		"client_secret": pi.ClientSecret,
	})
}

// writeReplay returns the idempotency-replay response for an existing session.
// It re-fetches the PaymentIntent to recover client_secret. If Stripe is
// unreachable, it returns 502 rather than silently omitting the secret — a
// client without client_secret cannot complete payment and would be stuck.
func (h *handler) writeReplay(w http.ResponseWriter, existing Session) {
	resp := map[string]any{"session": existing}
	if existing.StripePaymentIntentID != "" {
		pi, err := paymentintent.Get(existing.StripePaymentIntentID, nil)
		if err != nil {
			slog.Error("stripe paymentintent get failed on idempotency replay",
				"error", err,
				"session_id", existing.ID,
				"payment_intent_id", existing.StripePaymentIntentID)
			writeError(w, http.StatusBadGateway, "failed to retrieve payment intent for replay")
			return
		}
		resp["client_secret"] = pi.ClientSecret
	}
	writeJSON(w, http.StatusCreated, resp)
}

// checkIdempotencyMismatch returns a non-empty error string if the new
// request's contract fields differ from those stored in existing. It is a pure
// function so it can be unit-tested independently of the HTTP layer. Description
// is not a contract field and is intentionally ignored (matches Stripe's
// behaviour: description may differ across retries of the same key).
func checkIdempotencyMismatch(req *CreateSessionRequest, currency, channel string, existing Session) string {
	if req.AgentID != existing.AgentID ||
		req.AmountCents != existing.AmountCollectedCents ||
		currency != existing.Currency ||
		channel != existing.Channel {
		return fmt.Sprintf(
			"Idempotency-Key was first used with different parameters. Original request: agent_id=%s, amount_cents=%d, currency=%s, channel=%s. Use a different Idempotency-Key or send the same parameters as the original request.",
			existing.AgentID, existing.AmountCollectedCents, existing.Currency, existing.Channel,
		)
	}
	return ""
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
