package stripehandler

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"
	stripe "github.com/stripe/stripe-go/v82"
	"github.com/stripe/stripe-go/v82/webhook"

	"github.com/enkyuan/alloy/agentpay/api/internal/session"
	wh "github.com/enkyuan/alloy/agentpay/api/internal/webhook"
)

// Handler handles POST /stripe/webhook.
type Handler struct {
	webhookSecret string
	sessions      *session.Store
	webhooks      *wh.Store
}

// New creates a Stripe webhook handler.
func New(webhookSecret string, sessions *session.Store, webhooks *wh.Store) *Handler {
	return &Handler{
		webhookSecret: webhookSecret,
		sessions:      sessions,
		webhooks:      webhooks,
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
		h.handleSucceeded(r.Context(), event)
	case "payment_intent.payment_failed":
		h.handleFailed(r.Context(), event)
	}
	w.WriteHeader(http.StatusOK)
}

func (h *Handler) handleSucceeded(ctx context.Context, event stripe.Event) {
	var pi stripe.PaymentIntent
	if err := json.Unmarshal(event.Data.Raw, &pi); err != nil {
		slog.Error("unmarshal payment_intent", "err", err)
		return
	}

	summary := fmt.Sprintf("Payment of $%.2f completed", float64(pi.Amount)/100)
	if err := h.sessions.UpdateAfterPayment(ctx, pi.ID, "completed", summary, pi.Amount); err != nil {
		slog.Error("update session after payment", "pi_id", pi.ID, "err", err)
		return
	}

	sess, err := h.sessions.GetByPaymentIntent(ctx, pi.ID)
	if err != nil {
		slog.Error("get session by payment intent", "pi_id", pi.ID, "err", err)
		return
	}

	h.enqueueEvent(ctx, sess, "payment.completed", map[string]any{
		"session_id":   sess.ID,
		"amount_cents": pi.Amount,
		"currency":     string(pi.Currency),
		"status":       "completed",
	})
}

func (h *Handler) handleFailed(ctx context.Context, event stripe.Event) {
	var pi stripe.PaymentIntent
	if err := json.Unmarshal(event.Data.Raw, &pi); err != nil {
		slog.Error("unmarshal payment_intent", "err", err)
		return
	}

	if err := h.sessions.UpdateAfterPayment(ctx, pi.ID, "failed", "Payment failed - no charge made", 0); err != nil {
		slog.Error("update session after failure", "pi_id", pi.ID, "err", err)
		return
	}

	sess, err := h.sessions.GetByPaymentIntent(ctx, pi.ID)
	if err != nil {
		slog.Error("get session by payment intent", "pi_id", pi.ID, "err", err)
		return
	}

	h.enqueueEvent(ctx, sess, "payment.failed", map[string]any{
		"session_id": sess.ID,
		"status":     "failed",
	})
}

func (h *Handler) enqueueEvent(ctx context.Context, sess session.Session, eventType string, payload map[string]any) {
	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		slog.Error("marshal event payload", "err", err)
		return
	}

	// MVP: broadcast to all webhooks subscribed to this event across all orgs.
	// TODO: scope to org once session.Store exposes OrgIDForAgent.
	webhooks, err := h.webhooks.ListAllForEvent(ctx, eventType)
	if err != nil {
		slog.Error("list webhooks for event", "event", eventType, "err", err)
		return
	}

	for _, webhook := range webhooks {
		d := wh.Delivery{
			ID:          uuid.New().String(),
			WebhookID:   webhook.ID,
			EventType:   eventType,
			Payload:     payloadBytes,
			NextAttempt: time.Now().UTC(),
		}
		if err := h.webhooks.InsertDelivery(ctx, d); err != nil {
			slog.Error("insert delivery", "webhook_id", webhook.ID, "err", err)
		}
	}
}
