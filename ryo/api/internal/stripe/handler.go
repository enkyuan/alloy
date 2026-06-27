package stripehandler

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	stripe "github.com/stripe/stripe-go/v82"
	"github.com/stripe/stripe-go/v82/webhook"

	"github.com/enkyuan/alloy/ryo/api/internal/session"
	wh "github.com/enkyuan/alloy/ryo/api/internal/webhook"
)

// errAlreadyProcessed is a sentinel returned by ensureStripeEventNotProcessed
// when the event has already been committed. The caller commits the (empty) tx
// and returns nil to Stripe — an idempotent no-op.
var errAlreadyProcessed = errors.New("stripe event already processed")

// Handler handles POST /stripe/webhook.
type Handler struct {
	webhookSecret string
	sessions      *session.Store
	webhooks      *wh.Store
	db            *pgxpool.Pool
}

// New creates a Stripe webhook handler. db is used to begin a single tx that
// spans session update + webhook delivery enqueue, so neither can succeed
// without the other.
func New(webhookSecret string, sessions *session.Store, webhooks *wh.Store, db *pgxpool.Pool) *Handler {
	return &Handler{
		webhookSecret: webhookSecret,
		sessions:      sessions,
		webhooks:      webhooks,
		db:            db,
	}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		http.Error(w, "read body", http.StatusBadRequest)
		return
	}
	event, err := webhook.ConstructEvent(body, r.Header.Get("Stripe-Signature"), h.webhookSecret)
	if err != nil {
		slog.Warn("stripe webhook signature invalid", "err", err)
		http.Error(w, "invalid signature", http.StatusBadRequest)
		return
	}

	switch event.Type {
	case "payment_intent.succeeded":
		if err := h.handleSucceeded(r.Context(), event); err != nil {
			slog.Error("handle payment_intent.succeeded", "event_id", event.ID, "err", err)
			http.Error(w, "internal", http.StatusInternalServerError)
			return
		}
	case "payment_intent.payment_failed":
		if err := h.handleFailed(r.Context(), event); err != nil {
			slog.Error("handle payment_intent.payment_failed", "event_id", event.ID, "err", err)
			http.Error(w, "internal", http.StatusInternalServerError)
			return
		}
	}
	w.WriteHeader(http.StatusOK)
}

func (h *Handler) handleSucceeded(ctx context.Context, event stripe.Event) error {
	var pi stripe.PaymentIntent
	if err := json.Unmarshal(event.Data.Raw, &pi); err != nil {
		return fmt.Errorf("unmarshal payment_intent: %w", err)
	}
	summary := fmt.Sprintf("Payment of $%.2f completed", float64(pi.Amount)/100)
	return h.applyAndEnqueue(ctx, event.ID, string(event.Type), pi.ID, "completed", summary, pi.Amount, "payment.completed", map[string]any{
		"amount_cents": pi.Amount,
		"currency":     string(pi.Currency),
		"status":       "completed",
	})
}

func (h *Handler) handleFailed(ctx context.Context, event stripe.Event) error {
	var pi stripe.PaymentIntent
	if err := json.Unmarshal(event.Data.Raw, &pi); err != nil {
		return fmt.Errorf("unmarshal payment_intent: %w", err)
	}
	return h.applyAndEnqueue(ctx, event.ID, string(event.Type), pi.ID, "failed", "Payment failed - no charge made", 0, "payment.failed", map[string]any{
		"status": "failed",
	})
}

// stripeEventInfo carries the Stripe event identity fields into the tx helpers.
type stripeEventInfo struct {
	eventID   string
	eventType string
}

// paymentUpdate carries the session mutation parameters.
type paymentUpdate struct {
	piID         string
	status       string
	plainSummary string
	amountCents  int64
}

// webhookEvent carries the webhook enqueue parameters.
type webhookEvent struct {
	eventType    string
	extraPayload map[string]any
}

// applyAndEnqueue updates the session row, looks up the matching session,
// and inserts a delivery row per subscribed webhook — all inside one tx.
// If any step fails, the entire effect is rolled back so we never end up
// with a "session is completed but no webhook ever fired" state.
//
// The tx also dedups on stripeEventID: Stripe delivers at-least-once, and any
// 5xx response from this handler (including the ones we return on internal
// error) causes Stripe to retry. Without dedup, a retry would insert a
// second set of webhook_deliveries rows and merchants would receive the
// event twice. Rollback on any subsequent error is safe because the
// dedup insert is part of the same tx.
func (h *Handler) applyAndEnqueue(
	ctx context.Context,
	stripeEventID, stripeEventType string,
	piID, status, summary string,
	amountCents int64,
	eventType string,
	extraPayload map[string]any,
) error {
	tx, err := h.db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	// Rollback after commit is a no-op in pgx; the ctx-canceled error from
	// rollback during a canceled request is also benign and discarded here.
	defer func() { _ = tx.Rollback(ctx) }()

	evInfo := stripeEventInfo{eventID: stripeEventID, eventType: stripeEventType}
	if err := ensureStripeEventNotProcessed(ctx, tx, evInfo); err != nil {
		if errors.Is(err, errAlreadyProcessed) {
			// Idempotent no-op: event already committed. Commit the empty tx
			// (dedup INSERT did NOTHING) and return 200 to Stripe.
			return tx.Commit(ctx)
		}
		return err
	}

	update := paymentUpdate{piID: piID, status: status, plainSummary: summary, amountCents: amountCents}
	sess, err := updateSessionAndFetch(ctx, tx, h.sessions, update)
	if err != nil {
		return err
	}

	ev := webhookEvent{eventType: eventType, extraPayload: extraPayload}
	if err := enqueueWebhooks(ctx, tx, h.webhooks, sess, ev); err != nil {
		return err
	}

	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("commit: %w", err)
	}
	return nil
}

// ensureStripeEventNotProcessed inserts the event into processed_stripe_events.
// Returns errAlreadyProcessed (a sentinel) when the event has already been seen
// so the caller can commit the empty tx and short-circuit gracefully.
func ensureStripeEventNotProcessed(ctx context.Context, tx pgx.Tx, ev stripeEventInfo) error {
	var insertedID string
	err := tx.QueryRow(ctx, `
		INSERT INTO processed_stripe_events (event_id, event_type)
		VALUES ($1, $2)
		ON CONFLICT (event_id) DO NOTHING
		RETURNING event_id`, ev.eventID, ev.eventType).Scan(&insertedID)
	if err != nil {
		if err == pgx.ErrNoRows {
			slog.Info("stripe event already processed, skipping", "event_id", ev.eventID)
			return errAlreadyProcessed
		}
		return fmt.Errorf("dedup insert: %w", err)
	}
	return nil
}

// updateSessionAndFetch applies the payment update within tx and returns the
// resulting session row for use in subsequent enqueue steps.
func updateSessionAndFetch(ctx context.Context, tx pgx.Tx, sessions *session.Store, u paymentUpdate) (session.Session, error) {
	if err := sessions.UpdateAfterPaymentTx(ctx, tx, u.piID, u.status, u.plainSummary, u.amountCents); err != nil {
		return session.Session{}, fmt.Errorf("update session: %w", err)
	}
	sess, err := sessions.GetByPaymentIntentTx(ctx, tx, u.piID)
	if err != nil {
		return session.Session{}, fmt.Errorf("get session: %w", err)
	}
	return sess, nil
}

// enqueueWebhooks inserts a delivery row for every webhook subscribed to
// ev.EventType. Canonical keys (session_id) are written after copying
// extraPayload so they cannot be shadowed by a caller-supplied key.
func enqueueWebhooks(ctx context.Context, tx pgx.Tx, webhooks *wh.Store, sess session.Session, ev webhookEvent) error {
	// MVP: broadcast to all webhooks subscribed to this event across all orgs.
	// TODO: scope to org once session.Store exposes OrgIDForAgent.
	webhookRows, err := webhooks.ListAllForEventTx(ctx, tx, ev.eventType)
	if err != nil {
		return fmt.Errorf("list webhooks: %w", err)
	}

	// Build payload: copy extraPayload first, then set canonical keys so they
	// always win even if extraPayload contained a colliding key like "session_id".
	payload := make(map[string]any, len(ev.extraPayload)+1)
	for k, v := range ev.extraPayload {
		payload[k] = v
	}
	payload["session_id"] = sess.ID // canonical key; always wins

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal payload: %w", err)
	}

	now := time.Now().UTC()
	for _, webhookRow := range webhookRows {
		d := wh.Delivery{
			ID:          uuid.New().String(),
			WebhookID:   webhookRow.ID,
			EventType:   ev.eventType,
			Payload:     payloadBytes,
			NextAttempt: now,
		}
		if err := webhooks.InsertDeliveryTx(ctx, tx, d); err != nil {
			return fmt.Errorf("insert delivery: %w", err)
		}
	}
	return nil
}
